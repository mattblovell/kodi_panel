#
# MIT License
#
# Copyright (c) 2020  Matthew Lovell
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from luma.core.interface.serial import spi
from luma.core.render import canvas
from luma.lcd.device import ili9341

import signal
import sys
import RPi.GPIO as GPIO

from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont

from datetime import datetime, timedelta
from enum import Enum
import time
import logging
import requests
import json
import io
import re
import os

PANEL_VER = "v0.62"

base_url = "http://localhost:8080"   # running on same box as Kodi
rpc_url  = base_url + "/jsonrpc"
headers  = {'content-type': 'application/json'}

# Image handling
frameSize       = (320, 240)
thumb_height    = 140;
last_image_path = None
last_thumb      = None

# Thumbnail defaults
kodi_thumb      = "./images/kodi_thumb.jpg"
default_thumb   = "./images/music_icon.png"
default_airplay =  "./images/airplay_thumb.png"
special_re      = re.compile('^special:\/\/temp\/(airtunes_album_thumb\.(png|jpg))')

# Track info fonts
font      = ImageFont.truetype("fonts/FreeSans.ttf", 22, encoding='unic')
fontB     = ImageFont.truetype("fonts/FreeSansBold.ttf", 22, encoding='unic')
font_sm   = ImageFont.truetype("fonts/FreeSans.ttf", 18, encoding='unic')
font_tiny = ImageFont.truetype("fonts/FreeSans.ttf", 11, encoding='unic')

# Font for time and track
font7S    = ImageFont.truetype("fonts/DSEG14Classic-Regular.ttf", 32)
font7S_sm = ImageFont.truetype("fonts/DSEG14Classic-Regular.ttf", 11)
color7S   = 'SpringGreen'

# Pillow objects
image  = Image.new('RGB', (frameSize), 'black')
draw   = ImageDraw.Draw(image)

# Audio/Video codec lookup
codec_name = {
    "ac3"      : "DD",
    "eac3"     : "DD",
    "dtshd_ma" : "DTS-MA",
    "dca"      : "DTS",
    "truehd"   : "DD-HD",
    "aac"      : "AAC",
    "wmapro"   : "WMA",
    "mp3float" : "MP3",
    "flac"     : "FLAC",
    "alac"     : "ALAC",
    "vorbis"   : "OggV",
    "aac"      : "AAC",
    "pcm_s16be": "PCM",
    "mp2"      : "MP2",
    "pcm_u8"   : "PCM",
    "BXA"      : "BXA",    # used with AirPlay
    "dsd_lsbf_planar": "DSD",
}


# Info display mode.  The next() function serves to switch modes in
# response to screen touches.  The list is intended to grow, as other
# ideas for layouts are proposed.

class PDisplay(Enum):
    DEFAULT    = 0   # small art, elapsed time, track info
    FULLSCREEN = 1   # fullscreen cover art

    def next(self):
        cls = self.__class__
        members = list(cls)
        index = members.index(self) + 1
        if index >= len(members):
            index = 0
        return members[index]

# At startup, just use the default layout for audio info.  This
# setting, if serialized and stored someplace, could be made
# persistent across script invocations if desired.
display_mode = PDisplay.DEFAULT

# GPIO assignment for screen's touch interrupt (T_IRQ), using RPi.GPIO
# numbering.  Find a pin that's unused by luma.  The touchscreen chip
# in my display has its own internal pullup resistor, so below no
# pull-up is specified.
TOUCH_INT      = 19
USE_TOUCH      = True

screen_press   = False
screen_on      = False
screen_offtime = datetime.now()

# Finally, a handle to the ILI9341-driven SPI panel via luma
serial = spi(port=0, device=0, gpio_DC=24, gpio_RST=25,
             reset_hold_time=0.2, reset_release_time=0.2)
device = ili9341(serial, active_low=False, width=320, height=240,
#                 framebuffer="full_frame",
                 bus_speed_hz=32000000
                 )

# ----------------------------------------------------------------------------

# Render text at the specified location, truncating characters and
# placing final elipsis if the string is too wide to display in its
# entirety.
def truncate_text(pil_draw, xy, text, fill, font):
    truncating = 0
    new_text = text
    t_width, t_height = pil_draw.textsize(new_text, font)
    while t_width > (frameSize[0] - 20):
        truncating = 1
        new_text = new_text[:-1]
        t_width, t_height = pil_draw.textsize(new_text, font)
    if truncating:
        new_text += "\u2026"
    pil_draw.text(xy, new_text, fill, font)


# Draw a horizontal progress bar at the specified location.
def progress_bar(pil_draw, bgcolor, color, x, y, w, h, progress):
    pil_draw.rectangle((x,y, x+w, y+h),fill=bgcolor)

    if(progress<=0):
        progress = 0.01
    if(progress>1):
        progress=1
    w = w*progress
    pil_draw.rectangle((x,y, x+w, y+h),fill=color)


# Retrieve cover art or a default thumbnail.  Cover art gets resized
# to the provided thumb_size, but any default images are used as-is.
#
# Note that details of retrieval seem to differ depending upon whether
# Kodi is playing from its library, from UPnp/DLNA, or from Airplay.
#
# The global last_image_path is intended to let any given image file
# be fetched and resized just *once*.  Subsequent calls just reuse the
# same data, provided that the caller preserves and passes in
# prev_image.
#
# The info argument must be the result of an XBMC.GetInfoLabels
# JSON-RPC call to Kodi.
def get_artwork(info, prev_image, thumb_size):
    global last_image_path

    image_set = False
    if (info['MusicPlayer.Cover'] != '' and
        info['MusicPlayer.Cover'] != 'DefaultAlbumCover.png' and
        not special_re.match(info['MusicPlayer.Cover'])):

        image_path = info['MusicPlayer.Cover']
        #print("image_path : ", image_path) # debug info

        if (image_path == last_image_path and prev_image):
            # Fall through and just return prev_image
            image_set = True
        else:
            last_image_path = image_path
            if image_path.startswith("http://"):
                image_url = image_path
            else:
                payload = {
                    "jsonrpc": "2.0",
                    "method"  : "Files.PrepareDownload",
                    "params"  : {"path": image_path},
                    "id"      : 5,
                }
                response = requests.post(rpc_url, data=json.dumps(payload), headers=headers).json()
                #print("Response: ", json.dumps(response))

            if ('details' in response['result'].keys() and
                'path' in response['result']['details'].keys()) :
                image_url = base_url + "/" + response['result']['details']['path']
                #print("image_url : ", image_url) # debug info

            r = requests.get(image_url, stream = True)
            # check that the retrieval was successful
            if r.status_code == 200:
                try:
                    r.raw.decode_content = True
                    cover = Image.open(io.BytesIO(r.content))
                    # resize while maintaining aspect ratio
                    orig_w, orig_h = cover.size[0], cover.size[1]
                    shrink = (float(thumb_size)/orig_h)
                    new_width = int(float(orig_h)*float(shrink))
                    # just crop if the image turns out to be really wide
                    if new_width > thumb_size:
                        thumb = cover.resize((new_width, thumb_size), Image.ANTIALIAS).crop((0,0,140,thumb_size))
                    else:
                        thumb = cover.resize((new_width, thumb_size), Image.ANTIALIAS)
                    prev_image = thumb
                    image_set = True
                except:
                    cover = Image.open(default_thumb)
                    prev_image = cover
                    image_set = True

    # finally, if we still don't have anything, check if is Airplay active
    if not image_set:
        if special_re.match(info['MusicPlayer.Cover']):
            airplay_thumb = "/storage/.kodi/temp/" + special_re.match(info['MusicPlayer.Cover']).group(1)
            if os.path.isfile(airplay_thumb):
                last_image_path = airplay_thumb
            else:
                last_image_path = default_airplay
        else:
            # default image when no artwork is available
            last_image_path = default_thumb

        cover = Image.open(last_image_path)
        # resize while maintaining aspect ratio
        orig_w, orig_h = cover.size[0], cover.size[1]
        shrink = (float(thumb_size)/orig_h)
        new_width = int(float(orig_h)*float(shrink))
        # just crop if the image turns out to be really wide
        if new_width > thumb_size:
            thumb = cover.resize((new_width, thumb_size), Image.ANTIALIAS).crop((0,0,140,thumb_size))
        else:
            thumb = cover.resize((new_width, thumb_size), Image.ANTIALIAS)
        prev_image = thumb        
        image_set = True

    if image_set:
        return prev_image
    else:
        return None


# Kodi-polling and image rendering function
#
# Locations and sizes (aside from font size) are all hard-coded in
# this function.  If anyone wanted to be ambitious and accommodate
# some form of programmable layout, you would start here.  Otherwise,
# just adjust to taste and desired outcome!
#
def update_display():
    global last_image_path
    global last_thumb
    global screen_press
    global screen_on
    global screen_offtime
    global display_mode

    # Start with a blank slate
    draw.rectangle([(1,1), (frameSize[0]-1,frameSize[1]-1)], 'black', 'black')

    # Check if the screen_on time has expired
    if (screen_on and datetime.now() >= screen_offtime):
        screen_on = False
        device.backlight(False)

    # Ask Kodi whether anything is playing...
    payload = {
        "jsonrpc": "2.0",
        "method"  : "Player.GetActivePlayers",
        "id"      : 3,
    }
    response = requests.post(rpc_url, data=json.dumps(payload), headers=headers).json()

    if (len(response['result']) == 0 or
        response['result'][0]['type'] != 'audio'):
        # Nothing is playing or video is playing, but check for screen
        # press before proceeding
        last_image_path = None
        last_thumb = None

        if screen_press:
            device.backlight(True)
            screen_on = True
            screen_offtime = datetime.now() + timedelta(seconds=10)

        if screen_on:
            # Idle status screen

            payload = {
                "jsonrpc": "2.0",
                "method"  : "XBMC.GetInfoLabels",
                "params"  : {"labels": ["System.Uptime",
                                        "System.CPUTemperature",
                                        "System.Date",
                                        "System.Time",
                ]},
                "id"      : 10,
            }
            status_resp = requests.post(rpc_url, data=json.dumps(payload), headers=headers).json()
            #print("Response: ", json.dumps(response))
            status = status_resp['result']

            # Render screen
            kodi_icon = Image.open(kodi_thumb)
            image.paste(kodi_icon, (5, 5))
            draw.text(( 145, 5), "kodi_panel " + PANEL_VER, fill='yellow', font=font)
            draw.text((145,32), status['System.Time'], fill='white', font=font_sm)

            if len(response['result']) == 0:
                draw.text(( 145, 56), "Idle",  fill='white', font=font_sm)
            elif response['result'][0]['type'] != 'audio':
                draw.text(( 145, 56), "Video playing",  fill='white', font=font_sm)

            draw.text((5, 150), status['System.Date'], fill='white', font=font_sm)
            draw.text((5, 175), "Uptime: " + status['System.Uptime'], fill='white', font=font_sm)
            draw.text((5, 200), "CPU: " + status['System.CPUTemperature'], fill='white', font=font_sm)
        else:
            device.backlight(False)

    else:
        # Audio is playing!
        device.backlight(True)

        # Change display modes upon any screen press, forcing
        # a re-fetch of any artwork
        if screen_press:
            display_mode = display_mode.next()
            last_image_path = None
            last_thumb = None

        # Retrieve (almost) all desired info in a single JSON-RPC call
        payload = {
            "jsonrpc": "2.0",
            "method"  : "XBMC.GetInfoLabels",
            "params"  : {"labels": ["MusicPlayer.Title",
                                    "MusicPlayer.Album",
                                    "MusicPlayer.Artist",
                                    "MusicPlayer.Time",
                                    "MusicPlayer.Duration",
                                    "MusicPlayer.TrackNumber",
                                    "MusicPlayer.Property(Role.Composer)",
                                    "MusicPlayer.Codec",
                                    "MusicPlayer.Year",
                                    "MusicPlayer.Genre",
                                    "MusicPlayer.Cover",
            ]},
            "id"      : 4,
        }
        response = requests.post(rpc_url, data=json.dumps(payload), headers=headers).json()
        #print("Response: ", json.dumps(response))
        info = response['result']

        # Progress information in Kodi Leia must be fetched separately.  This
        # looks to be fixed in Kodi Matrix.
        payload = {
            "jsonrpc": "2.0",
            "method"  : "Player.GetProperties",
            "params"  : {
                "playerid": 0,
                "properties" : ["percentage"],
            },
            "id"      : "prog",
        }
        response = requests.post(rpc_url, data=json.dumps(payload), headers=headers).json()
        if 'percentage' in response['result'].keys():
            prog = float(response['result']['percentage']) / 100.0
        else:
            prog = -1;

        if display_mode == PDisplay.DEFAULT:
            # retrieve cover image from Kodi
            last_thumb = get_artwork(info, last_thumb, thumb_height)
            if last_thumb:
                image.paste(last_thumb, (5, 5))

            # progress bar, if percentage was available
            if prog != -1:
                if info['MusicPlayer.Time'].count(":") == 2:
                    # longer bar for longer displayed time
                    progress_bar(draw, 'dimgrey', color7S, 150, 5, 164, 4, prog)
                else:
                    progress_bar(draw, 'dimgrey', color7S, 150, 5, 104, 4, prog)

            # elapsed time
            draw.text(( 148, 14), info['MusicPlayer.Time'],  fill=color7S, font=font7S)

            # track number
            if info['MusicPlayer.TrackNumber'] != "":
                draw.text(( 148, 60), "Track", fill='white', font=font_tiny)
                draw.text(( 148, 73), info['MusicPlayer.TrackNumber'],  fill=color7S, font=font7S)

            # track title
            truncate_text(draw, (5, 152), info['MusicPlayer.Title'],  fill='white',  font=font)

            # album title and track artist or, if not available, composer
            truncate_text(draw, (5, 180), info['MusicPlayer.Album'],  fill='white',  font=font_sm)
            if info['MusicPlayer.Artist'] != "":
                truncate_text(draw, (5, 205), info['MusicPlayer.Artist'], fill='yellow', font=font_sm)
            elif info['MusicPlayer.Property(Role.Composer)'] != "":
                truncate_text(draw, (5, 205), "(" + info['MusicPlayer.Property(Role.Composer)'] + ")", fill='yellow', font=font_sm)

            # audio info
            codec = info['MusicPlayer.Codec']
            if info['MusicPlayer.Duration'] != "":
                draw.text(( 230, 60), info['MusicPlayer.Duration'], font=font_tiny)
            if codec in codec_name.keys():
                draw.text(( 230, 74), codec_name[codec], font=font_tiny)
            if info['MusicPlayer.Genre'] != "":
                draw.text(( 230, 88), info['MusicPlayer.Genre'][:15], font=font_tiny)
            if info['MusicPlayer.Year'] != "":
                draw.text(( 230, 102), info['MusicPlayer.Year'], font=font_tiny)

        elif display_mode == PDisplay.FULLSCREEN:
            # retrieve full-screen artwork
            last_thumb = get_artwork(info, last_thumb, frameSize[1]-5)
            if last_thumb:
                image.paste(last_thumb, (int((frameSize[0]-last_thumb.width)/2), int((frameSize[1]-last_thumb.height)/2)))

    # Output to OLED/LCD display and unconditionally
    # clear any screen press
    screen_press = False
    device.display(image)


# Interrupt callback target from RPi.GPIO for T_IRQ
def touch_callback(channel):
    global screen_press
    screen_press = True
    print(datetime.now(), "Touchscreen pressed")


def main():
    print(datetime.now(), "Starting")
    # turn down verbosity from http connections
    logging.basicConfig()
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    # setup T_IRQ as a GPIO interrupt, if enabled
    if USE_TOUCH:
        print(datetime.now(), "Setting up touchscreen interrupt")
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(TOUCH_INT, GPIO.IN)
        GPIO.add_event_detect(TOUCH_INT, GPIO.FALLING,
                              callback=touch_callback, bouncetime=300)

    # main communication loop
    while True:
        device.backlight(True)
        draw.rectangle([(1,1), (frameSize[0]-1,frameSize[1]-1)], 'black', 'black')
        draw.text(( 5, 5), "Waiting to connect with Kodi...",  fill='white', font=font)
        device.display(image)

        while True:
            # ensure Kodi is up and accessible
            payload = {
                "jsonrpc": "2.0",
                "method"  : "JSONRPC.Ping",
                "id"      : 2,
            }

            try:
                response = requests.post(rpc_url, data=json.dumps(payload), headers=headers).json()
                if response['result'] != 'pong':
                    print(datetime.now(), "Kodi not available via HTTP-transported JSON-RPC.  Waiting...")
                    time.sleep(5)
                else:
                    break
            except:
                time.sleep(5)
                pass

        print(datetime.now(), "Connected with Kodi.  Entering update_display() loop.")
        device.backlight(False)

        # Loop until Kodi goes away
        while True:
            try:
                update_display()
            except (ConnectionRefusedError,
                    requests.exceptions.ConnectionError):
                print(datetime.now(), "Communication disrupted.")
                break
            # This delay seems sufficient to have a (usually) smooth progress
            # bar and elapsed time update
            time.sleep(0.92)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        if USE_TOUCH:
            print(datetime.now(), "Removing touchscreen interrupt")
            GPIO.remove_event_detect(TOUCH_INT)
        GPIO.cleanup()
        print(datetime.now(), "Stopping")
        exit(0)
