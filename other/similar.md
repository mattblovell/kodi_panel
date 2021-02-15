# Similar Projects

Prior to developing kodi_panel, I tried to create a survey of existing display-related projects for Kodi 
other music players.  I kept an updated version of that summary on the CoreELEC forum for some time.  Here's
what I found ...

## Kodi-related


### LCDProc

An overloaded name, referring both to a C-based client/server program for driving LCD or OLED displays *and* 
a Python addon to Kodi that acts as another form of client for that C-based server.  (There was also an older 
LCDproc that was part of the original XBMC core.  The Python addon is intended to replace that.  The longevity 
of both projects means one can find a lot of hits when searching for them.  To me, that makes it hard to find 
what’s up-to-date.)

As of 2020, both are still getting commits.  The webpage for the C-based lcdproc doesn’t seem to have been updated 
for several years, though. The C client/server has support for a wide range of displays, including 
HD44780-based character LCDs and apparently some graphical displays as well.

Communication from the addon to the server is sockets based, making use of Python’s telnetlib.

Client/server program: [source](https://github.com/lcdproc/lcdproc), [webpage](http://lcdproc.org/)
Kodi addon: [source](https://github.com/herrnst/script.xbmc.lcdproc)


### OpenVFD

Python-based service addon for Kodi, by Arthur Liberman, that communicates to displays using C drivers.  Configs 
for the Odroid C2 support HD44780 LCDs and SSD130[69], SH1106 OLEDs.  A form of graphical support 
for the HD44780 displays exists, at least in the form of “big digits”.  Based on the name, I originally 
thought that this addon only supported a very-specific type of display, which was an error.

At least for the HD44780, the actual format of data displayed is handled by the C driver, making local 
customization not particularly easy.

Kodi addon: [source](https://github.com/arthur-liberman/service.openvfd), [config files](https://github.com/arthur-liberman/vfd-configurations)
C drivers: [source](https://github.com/arthur-liberman/linux_openvfd)

This addon has several CoreELEC and LibreELEC forum threads:

- [How to configure VFD](https://discourse.coreelec.org/t/how-to-configure-vfd/427) (CoreELEC)
- [LePotato & OpenVFD](https://discourse.coreelec.org/t/lepotato-openvfd/974) (CoreELEC)
- [LED (VFD) Displays in LibreELEC](https://forum.libreelec.tv/thread/11736-led-vfd-displays-in-libreelec/?pageNo=1)

### Odroid N2 OLED Driver

Python-based service addon for Kodi from @roidy, distinct from OpenVFD.  Supports SSD130[69] and 
SH1106-based OLED graphical displays.  (SSD1309 support is SPI-only as of this writing, but 
I2C should be possible.)

Kodi addon: [source](https://github.com/roidy/service.odroidn2.oled)


### KodiDisplayInfo

A completely separate Python program (not an addon) that queries Kodi (via JSON-RPC) for 
what's playing, apparently *including artwork*, and renders it to a TFT LCD display.  Display 
\duties are handled vi [pygame](https://www.pygame.org/wiki/about), which in turn depends upon the 
C-based Simple DirectMedia Layer ([libsdl](http://www.libsdl.org/)).   

The web page unfortunately suggests that the music view with cover thumbnail is a work-in-progress.  The most 
recent commit, as of this writing, is dated June 2017.  Still, the 
[KODI_WEBSERVER](https://github.com/bjoern-reichert/KodiDisplayInfo/blob/master/classes/KODI_WEBSERVER.py) 
class may be an interesting starting point; it doesn't seem like the artwork retrieval was ever implemented.

Python program: [source](https://github.com/bjoern-reichert/KodiDisplayInfo), [webpage](https://www.opendisplaycase.com/kodidisplayinfo-program.html)


### Kodisplay

A Python-based Kodi service addon also making use of [pygame](https://www.pygame.org/wiki/about) (and SDL) 
for displaying to a TFT LCD.  Looks like the idea was to have the layout of the displayed controlled via a 
`layout.xml` file.  Since it's an addon, details from Kodi are retrieved via InfoLabels.  The 
`music` section of the example includes this:
```
		<image path="$INFO[Player.Art(thumb)]">
```

As of this writing, the last commit is dated Dec 2016.

Kodi addon: [source](https://github.com/vitalogy/script.kodisplay)



## Other Music Players

### mpd_oled

Focused on the MPD audio distributions moOde, Volume, and RuneAudio.  Separate C-based program by Adrian Rossiter 
that supports SSD130[69] and S[S]H1106-based OLED displays.  Depends upon MPD integration to know music-player 
state and track information, and uses a named pipe (FIFO) to obtain a copy of audio data out of MPD for its 
spectrum display.

Each of those MPD-based distributions has a forum thread for this program.

The audio spectrum was originally leveraged from C.A.V.A., which obtained audio data from ALSA.  That approach 
is evidently temperamental, though, and the mpd_oled author doesn’t directly support it.

C program: [source](https://github.com/antiprism/mpd_oled)


### PydPiper

Standalone python program, using [luma.core](https://github.com/rm-hull/luma.core) and 
[luma.oled](https://github.com/rm-hull/luma.oled), for displaying track information from MPD in 
moOde, Volumio, and RuneAudio.  As of late 2020, supports HD44780 LCDs, SSD1306 panels (I2C only), 
and two Winstar display types.  Looks to have a fairly impressive approach to font support and, more 
interestingly, *page files* for the customization of display info.

Audiophonics (the French audio company) made a fork of pydPiper for the displays in their RASPDAC products.

Python program: [source](https://github.com/dhrone/pydPiper)


### Volumio Touchscreen

Instructions on how to enable a 3.5" Waveshare display within Volumio.  From what I can tell, both 
Volumio and moOde Audio have the option of driving a local display -- supported by running a web browser within X.

Volumio forum: [thread](https://community.volumio.org/t/volumio-with-3-5-tft-touch-screen-gpio-rpi-3b/11265)


### PyAudioTFT

Looks like a pygame-based Python script to present info from MPD.  Hasn't been updated since early 
2016, but the screen layout is nicely designed.

Python program: [source](https://github.com/jbltx/PyAudioTFT)


