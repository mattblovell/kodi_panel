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
#
# ----------------------------------------------------------------------------
#
# This script is intended to aid in development since, using pygame as
# a device emulator with luma.lcd, one can prototype layout choices,
# play with different fonts, etc.
#
# As currently written, the script must be copied to the
#
#   luma.examples/examples
#
# directory (after cloning it from github) and executed via a command
# like the following:
#
#   python luma_demo.py --display pygame --width 320 --height 240 --scale 1
#
# The font and image paths below are also "flat", with no subdirectory
# referenced.  So, those resources should also be copied into the
# luma.examples/examples directory, residing next to the script.
# We can change that if people actually start using this for
# prototyping and get annoyed by the extra step. 
#
# Screen touches are somewhat emulated below by checking for a pressed
# key via pygame's state.  The state is polled only once per update
# loop, though, so one must hold the button for a bit.
#
# Since this script is usually running on a desktop machine, you MUST
# also specify the current base_url to use below.
#
# ----------------------------------------------------------------------------


from demo_opts import get_device      # from luma.examples (REQUIRED FOR EMULATION)
from luma.core.render import canvas

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

# ----------------------------------------------------------------------------
PANEL_VER = "v0.67"

#base_url = "http://10.0.0.231:8080" # Raspberry Pi
base_url = "http://10.0.0.188:8080"  # Odroid C4
rpc_url  = base_url + "/jsonrpc"
headers  = {'content-type': 'application/json'}

# Image handling
frameSize       = (320, 240)
thumb_height    = 140;
last_image_path = ""
last_thumb      = ""

# Thumbnail defaults (these don't get resized)
kodi_thumb      = "./kodi_thumb.jpg"
default_thumb   = "./music_icon.png"
default_airplay =  "./airplay_thumb.png"

# RegEx for recognizing AirPlay images (compiled once)
special_re = re.compile(r'^special:\/\/temp\/(airtunes_album_thumb\.(png|jpg))')

# Track info fonts
font_main = ImageFont.truetype("FreeSans.ttf", 22, encoding='unic')
font_bold = ImageFont.truetype("FreeSansBold.ttf", 22, encoding='unic')
font_sm   = ImageFont.truetype("FreeSans.ttf", 18, encoding='unic')
font_tiny = ImageFont.truetype("FreeSans.ttf", 11)

# 7-Segment Font for time and track number
font7S    = ImageFont.truetype("DSEG14Classic-Regular.ttf", 32)
font7S_sm = ImageFont.truetype("DSEG14Classic-Regular.ttf", 11)

# Colors
color7S      = 'SpringGreen'   # 7-Segment color
color_progbg = 'dimgrey'       # progress bar background
color_progfg = color7S         # progress bar foreground
color_artist = 'yellow'       # artist name

image  = Image.new('RGB', (frameSize), 'black')
draw   = ImageDraw.Draw(image)

# Audio/Video codec lookup
codec_name = {"ac3"      : "DD",
              "eac3"     : "DD",
              "dtshd_ma" : "DTS-MA",
              "dca"      : "DTS",
              "truehd"   : "DD-HD",
              "aac"      : "AAC",
              "wmapro"   : "WMA",
              "mp3float" : "MP3",
              "flac"     : "FLAC",
              "BXA"      : "AirPlay",
              "alac"     : "ALAC",
              "vorbis"   : "OggV",
              "dsd_lsbf_planar": "DSD",
              "aac"      : "AAC",
              "pcm_s16be": "PCM",
              "mp2"      : "MP2",
              "pcm_u8"   : "PCM"}

# Touchscreen presses can somewhat be emulated by checking
# pygame for key presses.
screen_press   = False
screen_on      = False
screen_wake    = 15    # status screen waketime, in seconds
screen_offtime = datetime.now()

# Handle to pygame emulator
device = get_device()

# Info display mode
class PDisplay(Enum):
    DEFAULT    = 0   # small art, elapsed time, track info
    FULLSCREEN = 1   # fullscreen cover art
    FULL_PROG  = 2   # fullscreen art with vertical progress bar

    def next(self):
        cls = self.__class__
        members = list(cls)
        index = members.index(self) + 1
        if index >= len(members):
            index = 0
        return members[index]

display_mode = PDisplay.DEFAULT

#-----------------------------------------------------------------------------

# Render text at the specified location, truncating characters and
# placing a final ellipsis if the string is too wide to display in its
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


# Draw (by default) a horizontal progress bar at the specified
# location, filling from left to right.  A vertical bar can be drawn
# if specified, filling from bottom to top.
def progress_bar(pil_draw, bgcolor, color, x, y, w, h, progress, vertical=False):
    pil_draw.rectangle((x,y, x+w, y+h),fill=bgcolor)

    if progress <= 0:
        progress = 0.01
    if progress > 1:
        progress = 1

    if vertical:
        dh = h*progress
        pil_draw.rectangle((x,y+h-dh,x+w,y+h),fill=color)
    else:
        dw = w*progress
        pil_draw.rectangle((x,y, x+dw, y+h),fill=color)



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
    image_set     = False
    resize_needed = False

    cover = None   # retrieved artwork, original size
    thumb = None   # resized artwork

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
                #print("Response: ", json.dumps(response))  # debug info

                if ('details' in response['result'].keys() and
                    'path' in response['result']['details'].keys()) :
                    image_url = base_url + "/" + response['result']['details']['path']
                    #print("image_url : ", image_url) # debug info

            r = requests.get(image_url, stream = True)
            # check that the retrieval was successful before proceeding
            if r.status_code == 200:
                try:
                    r.raw.decode_content = True
                    cover = Image.open(io.BytesIO(r.content))
                    image_set     = True
                    resize_needed = True
                except:
                    cover = Image.open(default_thumb)
                    prev_image = cover
                    image_set     = True
                    resize_needed = False

    # finally, if we still don't have anything, check if is Airplay active
    if not image_set:
        resize_needed = False
        if special_re.match(info['MusicPlayer.Cover']):
            airplay_thumb = "/storage/.kodi/temp/" + special_re.match(info['MusicPlayer.Cover']).group(1)
            if os.path.isfile(airplay_thumb):
                last_image_path = airplay_thumb
                resize_needed   = True
            else:
                last_image_path = default_airplay
        else:
            # default image when no artwork is available
            last_image_path = default_thumb

        cover = Image.open(last_image_path)
        prev_image = cover
        image_set  = True

    # is resizing needed?
    if (image_set and resize_needed):
        # resize while maintaining aspect ratio, if possible
        orig_w, orig_h = cover.size[0], cover.size[1]
        shrink    = (float(thumb_size)/orig_h)
        new_width = int(float(orig_h)*float(shrink))
        # just crop if the image turns out to be really wide
        if new_width > thumb_size:
            thumb = cover.resize((new_width, thumb_size), Image.ANTIALIAS).crop((0,0,140,thumb_size))
        else:
            thumb = cover.resize((new_width, thumb_size), Image.ANTIALIAS)
        prev_image = thumb

    if image_set:
        return prev_image
    else:
        return None


def update_display():
    global last_image_path
    global last_thumb
    global screen_press
    global screen_on
    global screen_offtime
    global display_mode

    # Start with a blank slate
    draw.rectangle([(1,1), (frameSize[0]-2,frameSize[1]-2)], 'black', 'black')

    # Check if the screen_on time has expired
    if (screen_on and datetime.now() >= screen_offtime):
        screen_on = False
        #device.backlight(False)

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
            screen_press = False
            screen_on = True
            screen_offtime = datetime.now() + timedelta(seconds=screen_wake)

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
            draw.text(( 145, 5), "kodi_panel " + PANEL_VER, fill=color_artist, font=font_main)

            if len(response['result']) == 0:
                draw.text(( 145, 32), "Idle",  fill='white', font=font_sm)
            elif response['result'][0]['type'] != 'audio':
                draw.text(( 145, 32), "Video playing",  fill='white', font=font_sm)

            # time in 7-segment font
            time_parts = status['System.Time'].split(" ")
            time_width, time_height = draw.textsize(time_parts[0], font7S)
            draw.text((145,73), time_parts[0], fill=color7S, font=font7S)
            draw.text((145 + time_width + 5, 73), time_parts[1], fill=color7S, font=font7S_sm)

            draw.text((5, 150), status['System.Date'], fill='white', font=font_sm)
            draw.text((5, 175), "Up: " + status['System.Uptime'], fill='white', font=font_sm)
            draw.text((5, 200), "CPU: " + status['System.CPUTemperature'], fill='white', font=font_sm)
        else:
            draw.text(( 5, 5), "Nothing playing",  fill='white', font=font_main)

    else:
        # Something's playing!
#        device.backlight(True)

        # Change display modes upon any screen press, forcing
        # a re-fetch of any artwork
        if screen_press:
            screen_press = False
            display_mode = display_mode.next()
            last_image_path = None
            last_thumb = None
            print(datetime.now(), "Display mode switched to", display_mode.name)

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
                                    "Player.Art(thumb)",
            ]},
            "id"      : 4,
        }
        response = requests.post(rpc_url, data=json.dumps(payload), headers=headers).json()
        #print("Response: ", json.dumps(response))
        info = response['result']

        # progress information
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

        # Default display -- all info with small artwork
        if display_mode == PDisplay.DEFAULT:
            # retrieve cover image from Kodi, if it exists and needs a refresh
            last_thumb = get_artwork(info, last_thumb, thumb_height)
            if last_thumb:
                image.paste(last_thumb, (5, 5))

            # progress bar and elapsed time
            if prog != -1:
                if info['MusicPlayer.Time'].count(":") == 2:
                    # longer bar for longer displayed time
                    progress_bar(draw, color_progbg, color_progfg, 150, 5, 164, 4, prog)
                else:
                    progress_bar(draw, color_progbg, color_progfg, 150, 5, 104, 4, prog)

            draw.text(( 148, 14), info['MusicPlayer.Time'],  fill=color7S, font=font7S)

            # track number
            if info['MusicPlayer.TrackNumber'] != "":
                draw.text(( 148, 60), "Track", fill='white', font=font_tiny)
                draw.text(( 148, 73), info['MusicPlayer.TrackNumber'],  fill=color7S, font=font7S)

            # track title
            truncate_text(draw, (5, 152), info['MusicPlayer.Title'],  fill='white',  font=font_main)

            # other track information
            truncate_text(draw, (5, 180), info['MusicPlayer.Album'],  fill='white',  font=font_sm)
            if info['MusicPlayer.Artist'] != "":
                truncate_text(draw, (5, 205), info['MusicPlayer.Artist'], fill=color_artist, font=font_sm)
            elif info['MusicPlayer.Property(Role.Composer)'] != "":
                truncate_text(draw, (5, 205), "(" + info['MusicPlayer.Property(Role.Composer)'] + ")", fill=color_artist, font=font_sm)

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

        # Full-screen art
        elif display_mode == PDisplay.FULLSCREEN:
            # retrieve full-screen artwork
            last_thumb = get_artwork(info, last_thumb, frameSize[1]-5)
            if last_thumb:
                image.paste(last_thumb, (int((frameSize[0]-last_thumb.width)/2), int((frameSize[1]-last_thumb.height)/2)))

        # Full-screen art with progress bar
        elif display_mode == PDisplay.FULL_PROG:
            last_thumb = get_artwork(info, last_thumb, frameSize[1]-5)
            if last_thumb:
                image.paste(last_thumb, (int((frameSize[0]-last_thumb.width)/2), int((frameSize[1]-last_thumb.height)/2)))
            # vertical progress bar
            if prog != -1:
                progress_bar(draw, color_progbg, color_progfg, frameSize[0]-12, 1, 10, frameSize[1]-4, prog, vertical=True)

    # Output to OLED/LCD display
    device.display(image)


def main():
    global screen_press
    print(datetime.now(), "Starting")

    # Turn down verbosity from http connections
    logging.basicConfig()
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    while True:
        #device.backlight(True)
        draw.rectangle([(1,1), (frameSize[0]-2,frameSize[1]-2)], 'black', 'black')
        draw.text(( 5, 5), "Waiting to connect with Kodi...",  fill='white', font=font_main)
        device.display(image)

        while True:
            # first ensure Kodi is up and accessible
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

        print(datetime.now(), "Connected with Kodi.  Entering display loop.")
        #device.backlight(False)

        while True:
            try:
                keys = device._pygame.key.get_pressed()
                if keys[device._pygame.K_SPACE]:
                    screen_press = True
                    print(datetime.now(), "Touchscreen pressed (emulated)")
                update_display()
            except (ConnectionRefusedError,
                    requests.exceptions.ConnectionError):
                print(datetime.now(), "Communication disrupted.")
                break
            time.sleep(0.8)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(datetime.now(), "Removing touchscreen interrupt")
        print(datetime.now(), "Stopping")
        pass
