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

from demo_opts import get_device      # from luma.examples (REQUIRED FOR EMULATION)
from luma.core.render import canvas

from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont

from datetime import datetime
import time
import logging
import requests
import json
import io
import re
import os

#base_url = "http://10.0.0.231:8080" # Raspberry Pi
base_url = "http://10.0.0.188:8080"  # Odroid C4
rpc_url  = base_url + "/jsonrpc"
headers  = {'content-type': 'application/json'}

frameSize    = (320, 240)
thumb_height = 140;

last_image_path = ""
last_thumb      = ""

# Thumbnail defaults 
default_thumb   = "./music_icon.png"
default_airplay =  "./airplay_thumb.png"
special_re      = re.compile('^special:\/\/temp\/(airtunes_album_thumb\.(png|jpg))')                

# Audio/Video codec names
codec_name = {"ac3"      : "DD",
              "eac3"     : "DD",
              "dtshd_ma" : "DTS-MA",
              "dca"      : "DTS",
              "truehd"   : "DD-HD",
              "aac"      : "AAC",
              "wmapro"   : "WMA",
              "mp3float" : "MP3",
              "flac"     : "FLAC",
              "BXA"      : "BXA",
              "alac"     : "ALAC",
              "vorbis"   : "OggV",
              "dsd_lsbf_planar": "DSD",
              "aac"      : "AAC",
              "pcm_s16be": "PCM",
              "mp2"      : "MP2",
              "pcm_u8"   : "PCM"}

# Handle to pygame emulator
device = get_device()

# Track info fonts
font     = ImageFont.truetype("FreeSans.ttf", 22, encoding='unic')
fontB    = ImageFont.truetype("FreeSansBold.ttf", 22, encoding='unic')
font_sm  = ImageFont.truetype("FreeSans.ttf", 18, encoding='unic')
font_tiny = ImageFont.truetype("FreeSans.ttf", 11)

# Font for time and track
font7S    = ImageFont.truetype("DSEG14Classic-Regular.ttf", 32)
font7S_sm = ImageFont.truetype("DSEG14Classic-Regular.ttf", 11)

image  = Image.new('RGB', (frameSize), 'black')
draw   = ImageDraw.Draw(image)

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


def progress_bar(pil_draw, bgcolor, color, x, y, w, h, progress):
    pil_draw.ellipse((x+w,y,x+h+w,y+h),fill=bgcolor)
    pil_draw.ellipse((x,y,x+h,y+h),fill=bgcolor)
    pil_draw.rectangle((x+(h/2),y, x+w+(h/2), y+h),fill=bgcolor)

    if(progress<=0):
        progress = 0.01
    if(progress>1):
        progress=1
    w = w*progress
    pil_draw.ellipse((x+w,y,x+h+w,y+h),fill=color)
    pil_draw.ellipse((x,y,x+h,y+h),fill=color)
    pil_draw.rectangle((x+(h/2),y, x+w+(h/2), y+h),fill=color)


def update_display():
    global last_image_path
    global last_thumb
    draw.rectangle([(1,1), (frameSize[0]-2,frameSize[1]-2)], 'black', 'black')

    payload = {
        "jsonrpc": "2.0",
        "method"  : "Player.GetActivePlayers",
        "id"      : 3,
    }
    response = requests.post(rpc_url, data=json.dumps(payload), headers=headers).json()

    if len(response['result']) == 0:
        # Nothing playing
#        device.backlight(False)
        draw.text(( 5, 5), "Nothing playing",  fill='white', font=font)
        last_image_path = ""
        last_thumb = ""
    elif response['result'][0]['type'] != 'audio':
        # Not audio
#        device.backlight(False)
        draw.text(( 5, 5), "Not audio playing",  fill='white', font=font)
        last_image_path = ""
        last_thumb = ""
    else:
        # Something's playing!
#        device.backlight(True)

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

        # progress bar
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

        # retrieve cover image from Kodi, if it exists and needs a refresh
        image_set = False
        if (info['MusicPlayer.Cover'] != '' and
            info['MusicPlayer.Cover'] != 'DefaultAlbumCover.png' and
            not special_re.match(info['MusicPlayer.Cover'])):

            image_path = info['MusicPlayer.Cover']
            #print("image_path : ", image_path) # debug info

            if image_path == last_image_path:
                image_set = True
            else:
                last_image_path = image_path
                payload = {
                    "jsonrpc": "2.0",
                    "method"  : "Files.PrepareDownload",
                    "params"  : {"path": image_path},
                    "id"      : 5,
                }
                response = requests.post(rpc_url, data=json.dumps(payload), headers=headers).json()
                print("Response: ", json.dumps(response))
                
                if ('details' in response['result'].keys() and
                    'path' in response['result']['details'].keys()) :
                    image_url = base_url + "/" + response['result']['details']['path']
                    print("image_url : ", image_url) # debug info

                    r = requests.get(image_url, stream = True)
                    # check that the retrieval was successful
                    if r.status_code == 200:
                        try:
                            r.raw.decode_content = True
                            cover = Image.open(io.BytesIO(r.content))
                            # resize while maintaining aspect ratio
                            orig_w, orig_h = cover.size[0], cover.size[1]
                            shrink = (float(thumb_height)/orig_h)
                            new_width = int(float(orig_h)*float(shrink))
                            # just crop if the image turns out to be really wide
                            if new_width > 140:
                                thumb = cover.resize((new_width, thumb_height), Image.ANTIALIAS).crop((0,0,140,thumb_height))
                            else:
                                thumb = cover.resize((new_width, thumb_height), Image.ANTIALIAS)
                            last_thumb = thumb
                            image_set = True
                        except:
                            cover = Image.open(default_thumb)                            
                            last_thumb = cover
                            image_set = True


        if not image_set:
            # default image when no artwork is available
            last_image_path = default_thumb            
            # is Airplay active?
            if special_re.match(info['MusicPlayer.Cover']):
                airplay_thumb = "/storage/.kodi/temp/" + special_re.match(info['MusicPlayer.Cover']).group(1)
                if os.path.isfile(airplay_thumb):
                    last_image_path = airplay_thumb
                else:
                    last_image_path = default_airplay

            cover = Image.open(last_image_path)
            last_thumb = cover
            image_set = True

        if image_set:
            image.paste(last_thumb, (5, 5))

        # progress bar and elapsed time
        if prog != -1:
            if info['MusicPlayer.Time'].count(":") == 2:
                # longer bar for longer displayed time
                progress_bar(draw, 'grey', 'lightgreen', 150, 5, 160, 4, prog)
            else:
                progress_bar(draw, 'grey', 'lightgreen', 150, 5, 100, 4, prog)

        draw.text(( 148, 14), info['MusicPlayer.Time'],  fill='lightgreen', font=font7S)

        # track number
        if info['MusicPlayer.TrackNumber'] != "":
            draw.text(( 148, 60), "Track", fill='white', font=font_tiny)
            draw.text(( 148, 73), info['MusicPlayer.TrackNumber'],  fill='white', font=font7S)

        # track title
        truncate_text(draw, (5, 150), info['MusicPlayer.Title'],  fill='white',  font=font)

        # other track information
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
            
    # Output to OLED/LCD display
    device.display(image)


def main():
    print(datetime.now(), "Starting")

    # Turn down verbosity from http connections
    logging.basicConfig()
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    while True:
        #device.backlight(True)
        draw.rectangle([(1,1), (frameSize[0]-2,frameSize[1]-2)], 'black', 'black')
        draw.text(( 5, 5), "Waiting to connect with Kodi...",  fill='white', font=font)
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

        while True:
            try:
                update_display()
            except (ConnectionRefusedError,
                    requests.exceptions.ConnectionError):
                print(datetime.now(), "Communication disrupted.")
                break
            time.sleep(0.9)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(datetime.now(), "Stopping")        
        pass
