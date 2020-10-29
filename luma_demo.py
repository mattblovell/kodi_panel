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
PANEL_VER = "v0.82"

#base_url = "http://10.0.0.231:8080" # Raspberry Pi
base_url = "http://10.0.0.188:8080"  # Odroid C4
rpc_url  = base_url + "/jsonrpc"
headers  = {'content-type': 'application/json'}

# Image handling
frame_size      = (320, 240)
last_image_path = ""
last_thumb      = ""

# Thumbnail defaults (these don't get resized)
kodi_thumb      = "./kodi_thumb.jpg"
default_thumb   = "./music_icon.png"
default_airplay = "./airplay_thumb.png"

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
color7S       = '#00FF78'    # 7-Segment color (used 'SpringGreen' for a while)
color_progbg  = '#424242'    # progress bar background (used 'dimgrey' for a while)
color_progfg = color7S       # progress bar foreground
color_artist = 'yellow'      # artist name

image  = Image.new('RGB', (frame_size), 'black')
draw   = ImageDraw.Draw(image)

# Audio/Video codec lookup
codec_name = {"ac3"      : "DD",
              "eac3"     : "DD",
              "dtshd_ma" : "DTS-MA",
              "dca"      : "DTS",
              "truehd"   : "DD-HD",
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

# Audio screen enumeration
#
# The next() function serves to switch modes in response to screen
# touches.  The list is intended to grow, as other ideas for layouts
# are proposed.
class ADisplay(Enum):
    DEFAULT    = 0   # small artwork, elapsed time, track info
    FULLSCREEN = 1   # fullscreen cover artwork
    FULL_PROG  = 2   # fullscreen art with vertical progress bar

    def next(self):
        cls = self.__class__
        members = list(cls)
        index = members.index(self) + 1
        if index >= len(members):
            index = 0
        return members[index]

audio_dmode = ADisplay.DEFAULT


# Audio screen layouts, used by audio_screens()
AUDIO_LAYOUT = \
{ ADisplay.DEFAULT :
  {
    # Artwork position and size
    "thumb" : { "pos": (4, 7), "size": 140 },

    # Progress bar.  Two versions are possible, short and long,
    # depending upon the MusicPlayer.Time string
    "prog" : { "pos": (150, 7),
               "short_len": 104,  "long_len": 164,
               "height": 8 },

    # All other text fields, including any labels
    #
    # Removing fields can be accomplished just by commenting out the
    # corresponding entry in this array.  If a new field is desired,
    # then the JSON-RPC call made in update_display() likely needs to
    # be augmented first.
    #
    # Special treatment exists for 'codec' and 'artist'.
    #
    "fields" :
    [
        { "name": "MusicPlayer.Time",          "pos": (148, 21), "font": font7S, "fill":color7S },

        { "name":  "MusicPlayer.TrackNumber",  "pos": (148, 79),  "font": font7S,     "fill": color7S,
          "label": "Track",                   "lpos": (148, 65), "lfont": font_tiny, "lfill": "white" },

        { "name": "MusicPlayer.Duration", "pos": (230, 65), "font": font_tiny, "fill": "white" },
        { "name": "codec",                "pos": (230, 79), "font": font_tiny, "fill": "white" },
        { "name": "MusicPlayer.Genre",    "pos": (230, 93), "font": font_tiny, "fill": "white", "trunc":1 },
        { "name": "MusicPlayer.Year",     "pos": (230,107), "font": font_tiny, "fill": "white" },

        { "name": "MusicPlayer.Title",    "pos": (4, 152),  "font": font_main, "fill": "white", "trunc":1},
        { "name": "MusicPlayer.Album",    "pos": (4, 180),  "font": font_sm,   "fill": "white", "trunc":1 },
        { "name": "MusicPlayer.Artist",   "pos": (4, 205),  "font": font_sm,   "fill": color_artist, "trunc":1 },
    ]
  },

  ADisplay.FULLSCREEN :
  {
    # Artwork size, position is determined by centering
    "thumb"   : { "center": 1 , "size": frame_size[1]-6 },
  },

  ADisplay.FULL_PROG :
  {
    # Artwork size, position is determined by centering
    "thumb" : { "center": 1, "size": frame_size[1]-6 },

    # Vertical progress bar
    "prog" : { "pos": (frame_size[0]-12, 1),
               "len": 10,
               "height": frame_size[1]-4 ,
               "vertical": 1
    }
  },

}


# Layout control for status screen, used by status_screen()
STATUS_LAYOUT = \
{
    # Kodi logo.  Since Image.thumbnail() is used for resizing, the
    # image cannot be made larger than its original size.  It can be
    # reduced in size if needed, though.
    "thumb" : { "pos": (5, 5), "size": 128 },

    # All other text fields
    #
    # Removing fields can be accomplished just by commenting out the
    # corresponding entry in this array.  If a new field is desired,
    # then the JSON-RPC call made in update_display() likely needs to
    # be augmented first.
    #
    # Special treatment exists for several fields
    "fields" :
    [
        { "name": "version",       "pos": (145,  8), "font": font_main, "fill": color_artist },
        { "name": "summary",       "pos": (145, 35), "font": font_sm,   "fill": "white" },
        { "name": "time_hrmin",    "pos": (145, 73), "font": font7S,    "fill": color7S,  "smfont": font7S_sm },

        { "name": "System.Date",           "pos": (  5,150), "font": font_sm,   "fill": "white" },
        { "name": "System.Uptime",         "pos": (  5,175), "font": font_sm,   "fill": "white" },
        { "name": "System.CPUTemperature", "pos": (  5,200), "font": font_sm,   "fill": "white" },
    ]
}


#-----------------------------------------------------------------------------

# Maintain a short list of the most recently-truncated strings,
# for use by truncate_text()
last_trunc = []

# Render text at the specified location, truncating characters and
# placing a final ellipsis if the string is too wide to display in its
# entirety.
#
# In its present form, this function essentially only checks for
# extensions past the right-hand side of the screen.  That could
# be remedied, if needed, by passing in a maximum permitted width
# and using it.
def truncate_text(pil_draw, xy, text, fill, font):
    global last_trunc
    truncating = 0

    # Assume an upper bound on how many characters are even
    # possible to display
    new_text = text[0:59];

    # Check if we've already truncated this string
    for index in range(len(last_trunc)):
        if (new_text == last_trunc[index]["str"] and
            font == last_trunc[index]["font"]):
            new_text = last_trunc[index]["short_str"]
            if last_trunc[index]["truncating"]:
                new_text += "\u2026"
            pil_draw.text(xy, new_text, fill, font)
            return

    # Otherwise, try an initial rendering
    t_width, t_height = pil_draw.textsize(new_text, font)

    # Form an initial estimate for how many characters will fit
    avg_char = len(new_text) / t_width
    avail_width = frame_size[0] - 10
    num_chars = int( (avail_width + 20) / avg_char )
    new_text = new_text[0:num_chars]

    # Now perform naive truncation.  A binary search would
    # be faster, if further speed is needed
    t_width, t_height = pil_draw.textsize(new_text, font)
    while (xy[0] + t_width) > avail_width:
        truncating = 1
        new_text = new_text[:-1]
        t_width, t_height = pil_draw.textsize(new_text, font)

    disp_text = new_text
    if truncating:
        disp_text += "\u2026"
    pil_draw.text(xy, disp_text, fill, font)

    # Store results for later consultation
    new_result = {
        "str"        : text[0:59],
        "short_str"  : disp_text,
        "truncating" : truncating,
        "font"       : font
        }
    last_trunc.insert(0, new_result)
    last_trunc = last_trunc[:9]


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
        # resize while maintaining aspect ratio, which should
        # be precisely what thumbnail accomplishes
        cover.thumbnail((thumb_size, thumb_size))
        prev_image = cover

    if image_set:
        return prev_image
    else:
        return None


# Idle status screen (shown upon a screen press)
#
# First argument is a Pillow ImageDraw object.
# Second argument is a dictionary loaded from Kodi system status fields.
# This argument is the string to use for current state of the system
#
def status_screen(draw, kodi_status, summary_string):
    layout = STATUS_LAYOUT

    str_prefix = {
        "System.Date"           : "",
        "System.Uptime"         : "Up: ",
        "System.CPUTemperature" : "CPU: ",
    }

    # kodi logo, if desired
    if "thumb" in layout.keys():
        kodi_icon = Image.open(kodi_thumb)
        kodi_icon.thumbnail((layout["thumb"]["size"], layout["thumb"]["size"]))
        image.paste(kodi_icon, layout["thumb"]["pos"])

    # go through all the text fields, if any
    if "fields" not in layout.keys():
        return

    txt_field = layout["fields"]

    for index in range(len(txt_field)):
        if txt_field[index]["name"] == "version":
            draw.text(txt_field[index]["pos"], "kodi_panel " + PANEL_VER,
                      txt_field[index]["fill"], txt_field[index]["font"])

        elif txt_field[index]["name"] == "summary":
            draw.text(txt_field[index]["pos"], summary_string,
                      txt_field[index]["fill"], txt_field[index]["font"])

        elif txt_field[index]["name"] == "time_hrmin":
            # time, in 7-segment font by default
            time_parts = kodi_status['System.Time'].split(" ")
            time_width, time_height = draw.textsize(time_parts[0], font7S)
            draw.text(txt_field[index]["pos"], time_parts[0],
                      txt_field[index]["fill"], txt_field[index]["font"])
            draw.text((txt_field[index]["pos"][0] + time_width + 5, txt_field[index]["pos"][1]),
                      time_parts[1],
                      txt_field[index]["fill"], txt_field[index]["smfont"])

        else:
            display_string = kodi_status[txt_field[index]["name"]]
            if txt_field[index]["name"] in str_prefix.keys():
                display_string = str_prefix[txt_field[index]["name"]] + display_string

            draw.text(txt_field[index]["pos"], display_string,
                      txt_field[index]["fill"], txt_field[index]["font"])



# Audio info screens (shown when music is playing).  With the
# introduction of the AUDIO_LAYOUT data structure, all 3 modes are
# handled here in this function.
#
# First two arguments are Pillow Image and ImageDraw objects.
# Third argument is a dictionary loaded from Kodi with relevant track fields.
# Fourth argument is a float representing progress through the track.
#
def audio_screens(image, draw, info, prog):
    global audio_dmode
    global last_thumb
    global last_image_path

    # Get layout details for this mode
    layout = AUDIO_LAYOUT[audio_dmode]

    # retrieve cover image from Kodi, if it exists and needs a refresh
    if "thumb" in layout.keys():
        last_thumb = get_artwork(info, last_thumb, layout["thumb"]["size"])
        if last_thumb:
            if "center" in layout["thumb"].keys():
                image.paste(last_thumb,
                            (int((frame_size[0]-last_thumb.width)/2),
                             int((frame_size[1]-last_thumb.height)/2)))
            else:
                image.paste(last_thumb, layout["thumb"]["pos"])
    else:
        last_thumb = None

    # progress bar
    if (prog != -1 and "prog" in layout.keys()):
        if "vertical" in layout["prog"].keys():
            progress_bar(draw, color_progbg, color_progfg,
                         layout["prog"]["pos"][0], layout["prog"]["pos"][1],
                         layout["prog"]["len"],
                         layout["prog"]["height"],
                         prog, vertical=True)
        elif info['MusicPlayer.Time'].count(":") == 2:
            # longer bar for longer displayed time
            progress_bar(draw, color_progbg, color_progfg,
                         layout["prog"]["pos"][0], layout["prog"]["pos"][1],
                         layout["prog"]["long_len"], layout["prog"]["height"],
                         prog)
        else:
            progress_bar(draw, color_progbg, color_progfg,
                         layout["prog"]["pos"][0], layout["prog"]["pos"][1],
                         layout["prog"]["short_len"], layout["prog"]["height"],
                         prog)

    # text fields, if there are any
    if "fields" not in layout.keys():
        return

    txt_field = layout["fields"]
    for index in range(len(txt_field)):

        # special treatment for codec, which gets a lookup
        if txt_field[index]["name"] == "codec":
            if info['MusicPlayer.Codec'] in codec_name.keys():
                draw.text(txt_field[index]["pos"],
                          codec_name[info['MusicPlayer.Codec']],
                          fill=txt_field[index]["fill"],
                          font=txt_field[index]["font"])

        # special treatment for MusicPlayer.Artist
        elif txt_field[index]["name"] == "artist":
            display_string = None
            if info['MusicPlayer.Artist'] != "":
                display_string = info['MusicPlayer.Artist']
            elif info['MusicPlayer.Property(Role.Composer)'] != "":
                display_string =  "(" + info['MusicPlayer.Property(Role.Composer)'] + ")"

            if display_string:
                if "trunc" in txt_field[index].keys():
                    truncate_text(draw, txt_field[index]["pos"],
                                  display_string,
                                  fill=txt_field[index]["fill"],
                                  font=txt_field[index]["font"])
                else:
                    draw.text(txt_field[index]["pos"],
                              display_string,
                              fill=txt_field[index]["fill"],
                              font=txt_field[index]["font"])

        # all other fields
        else:
            if (txt_field[index]["name"] in info.keys() and
                info[txt_field[index]["name"]] != ""):
                # ender any label first
                if "label" in txt_field[index]:
                    draw.text(txt_field[index]["lpos"], txt_field[index]["label"],
                              fill=txt_field[index]["lfill"], font=txt_field[index]["lfont"])
                # now render the field itself
                if "trunc" in txt_field[index].keys():
                    truncate_text(draw, txt_field[index]["pos"],
                                  info[txt_field[index]["name"]],
                                  fill=txt_field[index]["fill"],
                                  font=txt_field[index]["font"])
                else:
                    draw.text(txt_field[index]["pos"],
                              info[txt_field[index]["name"]],
                              fill=txt_field[index]["fill"],
                              font=txt_field[index]["font"])


# Kodi-polling and image rendering function
#
# Determine Kodi state and, if something of interest is playing,
# retrieve all the relevant information and get it drawn.
def update_display():
    global audio_dmode
    global screen_press
    global screen_on
    global screen_offtime
    global last_image_path
    global last_thumb

    # Start with a blank slate
    draw.rectangle([(0,0), (frame_size[0],frame_size[1])], 'black', 'black')

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
            if len(response['result']) == 0:
                summary = "Idle"
            elif response['result'][0]['type'] == 'video':
                summary = "Video playing"
            elif response['result'][0]['type'] == 'picture':
                summary = "Photo viewing"

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
            status_screen(draw, status_resp['result'], summary)
        else:
            draw.text(( 5, 5), "Nothing playing",  fill='white', font=font_main)

    else:
        # Something's playing!
#        device.backlight(True)

        # Change display modes upon any screen press, forcing
        # a re-fetch of any artwork
        if screen_press:
            screen_press = False
            audio_dmode = audio_dmode.next()
            last_image_path = None
            last_thumb = None
            print(datetime.now(), "Display mode switched to", audio_dmode.name)

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
        track_info = response['result']

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
        prog_response = requests.post(rpc_url, data=json.dumps(payload), headers=headers).json()
        if ('result' in prog_response.keys() and 'percentage' in prog_response['result'].keys()):
            prog = float(prog_response['result']['percentage']) / 100.0
        else:
            prog = -1

        # Audio info
        audio_screens(image, draw, track_info, prog)

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
        draw.rectangle([(0,0), (frame_size[0],frame_size[1])], 'black', 'black')
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
