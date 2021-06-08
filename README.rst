kodi_panel
==========

Kodi_panel is a standalone Python 3 script that provides an
information front panel for `Kodi® <https://kodi.tv/>`_ via an attached LCD display.  The LCD
is handled entirely by `luma.core <https://github.com/rm-hull/luma.core/>`_
and `luma.lcd <https://github.com/rm-hull/luma.lcd/>`_, which in turn
depend upon `Pillow <https://python-pillow.org/>`_ and `RPi.GPIO
<https://pypi.org/project/RPi.GPIO/>`_.  Information and album cover artwork
is retrieved from Kodi using
`JSON-RPC <https://kodi.wiki/view/JSON-RPC_API>`_.  The contents shown on the
display are configured via a 
`TOML <https://toml.io/en/>`_ setup file, intended to be easily customized.

The script is generally intended to run on the same SBC (single-board
computer) on which Kodi itself is running.  That's not really
necessary, though, provided one is willing to let the JSON-RPC calls
occur over the network.  The display attachment interface, particularly
if wanting to use HDMI, strongly affects possible setups.

**Disclaimer:** This project is *not* directly associated with either
`Kodi <https://kodi.tv/>`_ or
`CoreELEC <https://coreelec.org/>`_.  Kodi is a registered trademark
of the XBMC Foundation.  Fonts are redestributed under either the
SIL Open Font License or Apache 2.0; see 
`fonts/sources.txt <https://github.com/mattblovell/kodi_panel/blob/master/fonts/sources.txt>`_ 
for further information.  Album and movie cover art (in photos or in emulator
screenshots) is *not* a part of kodi_panel and is shown under the Fair Use doctrine.

.. image:: https://raw.github.com/mattblovell/kodi_panel/master/extras/working_lcd.jpg


The general approach taken by this project, running separately from Kodi
and retrieving all relevant state via JSON-RPC, has been used by 
`other projects <https://github.com/mattblovell/kodi_panel/blob/master/other/similar.md>`_.
The main advantage of *not* being a Kodi addon is that, at least
with Kodi Leia, one is no longer restricted to Python 2.  Being a standalone
script also means that one can have a separate SBC driving a "Now Playing"
screen anywhere one would like.  

If you are familiar with reading and writing Python, and making use of the Pillow
image library, it should be straightforward to modify kodi_panel to your taste
or needs.  Using Python also lets one experiment with and inspect the
results of the JSON-RPC calls to Kodi.  The Kodi documentation
on
`JSON-RPC <https://kodi.wiki/view/JSON-RPC_API>`_, 
`InfoLabels <https://kodi.wiki/view/InfoLabels>`_, and
`InfoBooleans <https://kodi.wiki/view/List_of_boolean_conditions>`__ 
should give you a complete picture of what information is available.
(One can also change Kodi's state using JSON-RPC, something I don't even
attempt here.)

The ``setup.toml`` file provides control over fonts, font sizes, colors, default images, and
the layout of elements on the display.  Several hooks for callback functions 
also exist throughout the main ``kodi_panel_display.py`` file.  One can 
customize many aspects of the display screens via additions to the 
very short startup scripts, rather than modifying ``kodi_panel_display.py`` itself.
(Look for the long comment blocks describing the ``ELEMENT_CB`` and 
``STRING_CB`` dictionaries and the currently-implemented callbacks for details.)

Running on an Odroid C4 with a 320x480 SPI display, kodi_panel appears to 
take ~0.5% of CPU time when idle and about ~2.5% when music playback is 
occurring.  Kodi itself, for comparison, takes 3% CPU when idle and 
8% when busy (for ALAC playback).

This CPU load increases when running remotely from Kodi and as
the display size increases.  For a 800x480 HDMI display using network
calls to query Kodi state, the active load increases to 12 to 15%
running on an RPi 3.  Using an RPi Zero to drive that same
display, the active CPU load goes up to 25%, with an idle load in the 
11% to 14% range.

If you're interested in learning the development history of kodi_panel, 
you can read through these two discussions in CoreELEC's forums:

- `Graphical front panel display <https://discourse.coreelec.org/t/graphical-front-panel-display/12932>`_
- `RPi-GPIO-Odroid & Python Pillow <https://discourse.coreelec.org/t/rpi-gpio-odroid-python-pillow/13088>`_


Installation
------------

Kodi setup
**********

Before proceeding, a few minor setup changes may be necessary for your 
Kodi installation:

- For JSON-RPC calls to work over HTTP transport, Kodi's 
  `web server <https://kodi.wiki/view/Webserver#Enabling_the_webserver>`_ must be enabled.
  See the brief instructions at that link for details.  (I've not experimented with
  the authentication option that is available; if anyone tries it and has suggestions
  for necessary code changes, please let me know.)

- Artwork is retrieved over the network via Kodi's
  `Virtual File System <https://kodi.wiki/view/Webserver#Virtual_File_System_.2Fvfs>`_ (vfs).
  Starting with the XBMC release in 2013, vfs provides access to files *only* if
  the path is enabled as a *media source* (i.e., a path enabled for video, music,
  photos, or programs).  If you encounter any issues with artwork retrieval
  for kodi_panel, be sure to examine how Kodi's media sources are configured.

  - For AirPlay cover art, Kodi makes use of a file in temporary storage,
    specifically ``special://temp/airtunes_album_thumb.jpg`` or a similar PNG file.
    The ``special://temp`` path must be added as a media source (not just a file browser
    source) if one wants AirPlay cover art to be functional running on a separate
    SBC from Kodi.  (If kodi_panel is running on the same SBC as Kodi, local file
    system access suffices.)


GPIOs
*****

When I started, I only had direct access to a Raspberry Pi 3 Model B and an Odroid C4.
I subsequently got the script running on an RPi 4 Model B and an 
RPi Zero W.  As others try additional SBCs, please feel free to suggest additions or
changes to this documentation.

The first step is really to get your display of choice connected and
working.  For a SPI-attached display, a prequisite is therefore 
understanding the GPIO pinout of your SBC.  
Be aware the GPIO pins have both *physical* numbers and numbers
or names as assigned by whatever software one happens to be using to
control and access them.  Since luma.lcd makes use of RPi.GPIO, the
numbers you'll see in the code or in setup files all correspond to RPi.GPIO's
numbering scheme (which is derived from the Broadcom chip that drives
the pins).  Fortunately, that scheme is well-documented all over the
web, for instance at this `SparkFun GPIO
<https://learn.sparkfun.com/tutorials/raspberry-gpio/gpio-pinout>`_
page.

On another note, for *all* the display modules that I tried before first 
settling on the ili9341-based LCDs, I only ever tried using 3.3V for Vcc.  This
avoided having to worry about `level shifters <https://www.adafruit.com/product/1875>`_.
Be careful wiring up your SBC; if you're not familiar with them
generally, see the warnings documented on the RPi
`GPIO usage <https://www.raspberrypi.org/documentation/usage/gpio/>`_ page.

Of course, the GPIO pins aren't very interesting if you're using an HDMI-attached
display (unless you would like to control the backlight for such a display).


Raspberry Pi
************

The directions below were tried on an RPi3 Model B v1.2 using Raspberry Pi OS
(Buster) with Linux kernel 5.4.51-v7+ in late 2020.  (I've *not* tried getting
the display working with LibreELEC.)

For Raspberry Pi boards, follow the
`installation directions <https://luma-lcd.readthedocs.io/en/latest/>`_ from
luma.lcd to get your display working.  Luma's directions are thorough
and provide suggested wiring for a number of displays.  You can make
use of `luma.examples <https://github.com/rm-hull/luma.examples>`_
to test and exercise the display.  The installation directions assume
you are running a fairly complete Linux distribution, such as
`Raspberry Pi OS <https://www.raspberrypi.org/downloads/raspberry-pi-os/>`_.

Once you have the luma.examples working, you're really about done!
Install Kodi as well, and get it working as desired.  Two additional
Python modules are needed:

::
   
   pip3 install toml aenum


The ``example_setup_320x240.toml`` file should be copied to ``setup.toml``
and edited as appropriate for your needs.  Additional example files at other
display resolutions are also available.  If kodi_panel is to run on
the same SBC as hosting the display, the ``BASE_URL`` within ``setup.toml``
can be left using ``localhost``.  Otherwise, set it as needed.

Afer that, try starting kodi_panel.  Assuming you are using an ili9341-based
display, that's accomplished by invoking

::

  python3 kodi_panel_ili9341.py


when in the ``kodi_panel`` directory.  You may wish to create a softlink
named simply ``kodi_panel.py``, just for convenience.
  
At the moment, I have forgotten whether any other the additional
packages used in ``kodi_panel_display.py`` come with Python or have to
be installed, aside from toml and aenum listed above.  It is certainly
possible that you'll have to add additional (pure Python) packages via
``pip``, such as

::

  pip3 install requests

Ideally, upon startup you will then see the start of kodi_panel's
log-style standard output:

::

  2020-10-16 09:29:54.233730 Starting
  2020-10-16 09:29:54.234313 Setting up touchscreen interrupt
  2020-10-16 09:29:54.293762 Connected with Kodi.  Entering update_display() loop.

Alternatively, you can instead make use of ``kodi_panel.service`` and systemd.
On Raspberry Pi OS, copy that example service file to ``/etc/systemd/service`` 
and then invoke

::

  sudo systemctl enable kodi_panel

Other OSes with systemd may have a different location for such service files.
Running as a service is useful when kodi_panel is *not* running 
on the same SBC as Kodi.  As written, the service file starts up the
framebuffer version of kodi_panel.  Naturally, you can edit the service file to 
match your needs.


Odroid C4
*********

The instructions below worked for CoreELEC 9.2.x (Kodi 18, Linux 4.9.113) on an Odroid C4. 
For Raspberry Pi boards and SPI-attached displays, RPi.GPIO obviously works as-is.  
For Odroid boards, one must instead make use of
`RPi.GPIO-Odroid <https://github.com/awesometic/RPi.GPIO-Odroid>`_.

Hardkernel maintains information regarding the GPIO headers for their various
boards on the `Odroid Wiki <https://wiki.odroid.com/>`_.  I consulted
that wiki, for instance, for the C4's
`J2 expansion header <https://wiki.odroid.com/odroid-c4/hardware/expansion_connectors>`_ pinout.
Each board also has an application_note section in which GPIOs are discussed further.
Note, however, that the discussion there typically assumes that one is running a fairly
complete Linux -- that's not exactly what CoreELEC is.
  
`CoreELEC <https://coreelec.org/>`_, true to its tagline, is a "just enough OS".
That means that a typical CoreELEC installation does *not* provide ``apt``,
or ``git``, or the tool pipeline and header files one typically uses for code development.
All is not lost, though, for the CoreELEC developers do make it extremely
easy to install `Entware <https://github.com/Entware/Entware/wiki>`_.  With
that, you can get a "just enough" development environment!

It may be necessary to enable the SPI bus in CoreELEC's kernel.  That can be accomplished
by activating the relevant entries that exist within the Device Tree, by executing
these commands:

1. ``mount -o remount,rw /flash``
2. ``fdtput -t s /flash/dtb.img /soc/cbus@ffd00000/spi@13000/spidev@0 status "okay"``
3. ``fdtput -t s /flash/dtb.img /soc/cbus@ffd00000/spi@13000 status "okay"``

Note that the above steps must be repeated anytime CoreELEC is upgraded in-place.
(The rest of the installation appears to be left untouched by such an upgrade.)

Next, create the file ``/etc/modules-load.d/spi.conf`` such that it contains these two lines:

::

  spidev
  spi_meson_spicc

and reboot.  After the reboot, the device file ``/dev/spidev0.0`` should exist.

The next immediate goal is still the same as it was on the RPi -- get luma.lcd 
installed and talking to your display.  There are just a few more steps necessary to 
achieve that goal than if you had armbian or Debian installed.  (I'm not going to 
describe how to secure-shell (ssh) into your CoreELEC SBC; you should
be able to find details on that elsewhere on the web.)
Here are the steps I ended up using, as captured from the second forum thread
above.  Note that the ``python3`` and ``pip3`` commands below are all
expected to make use of files newly-installed out in ``/storage/opt``
as a consequence of the Entware installation.


1. Install Entware, as described in this `post <https://discourse.coreelec.org/t/what-is-entware-and-how-to-install-uninstall-it/1149>`_, via ``installentware``.

2. Install git, python3, and other development tools and convenience tools:

   ::

     opkg update
     opkg install git git-http
     opkg install gcc
     opkg install busybox ldd make gawk sed
     opkg install path diffutils coreutils-install
     opkg install python3 python3-dev python3-pip

3. Install `RPi.GPIO-Odroid <https://github.com/awesometic/RPi.GPIO-Odroid>`_:

   ::

     git clone https://github.com/awesometic/RPi.GPIO-Odroid.git
     cd RPi.GPIO-Odroid/
     python3 setup.py build
     python3 setup.py install

4. Install the entware-compiled version of Pillow:

   ::

     opkg install python3-pillow

5. You should then be able install luma.lcd in basically the usual fashion:

   ::

     pip3 install luma.lcd

6. Install additional Python modules:

   ::
      
     pip3 install toml aenum

7. In the ``kodi_panel/`` directory, copy and rename
   ``example_setup_320x240.toml`` to ``setup.toml``.  Open the file
   for editing, checking that at least ``BASE_URL`` and display width
   and height are correct.  (A few example setup files at other
   resolutions are also available.)
     
Assuming the above is all successful, you should now be able to
run any of the demonstrations from luma.examples.  If Kodi is up
and running (it is CoreELEC, after all), one can ``cd`` into
kodi_panel's directory and invoke

::

  /opt/bin/python3 kodi_panel_ili9341.py

Now, try playing something!

As with the RPi steps above, it is possible that some additional 
(pure Python) packages are needed by kodi_panel, such that you'll
find yourself adding them with commands such as:

::

  /opt/bin/pip3 install requests  

To have kodi_panel start up when the Odroid is powered-on, I take advantage
of Kodi's ``autostart.sh`` mechanism.  An example file is provided as part
of kodi_panel.

I have only tried the above on an Odroid C4.  If others want to inform me of their
attempts and what instruction changes need to be captured, please let me know.


Other Details
-------------

Touch Interrupt
***************

For the 3.2-inch ILI9341-based board that I initially tried, the touch
controller (XPT2046) was alive following power-up such that
T_IRQ, the touch interrupt, was working!  It was not necessary to send
any command to the controller or even connect T_CLK.  The T_IRQ signal
is by default pulled up to Vcc by an internal resistor and gets pulled
down to ground when the screen is pressed (as verified with a simple
multimeter).

This was all the motivation I needed to give it a try.

All that was necessary was to find a GPIO pin that was free to use an
an input.  For my Odroid C4 board, that turned out to be GPIO19, otherwise
known as Pin Number 35.  On the RPi3, GPIO16 (physical Pin 36) worked.

The following block of code from ``kodi_panel_display.py`` is qualified by a
USE_TOUCH boolean that is set according to ``setup.toml`` configuration. If you
are *not* using the touch interrupt, just set the relevant variable to
``false`` in the TOML file.

::

    # setup T_IRQ as a GPIO interrupt, if enabled
    if USE_TOUCH:
        print(datetime.now(), "Setting up touchscreen interrupt")
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(TOUCH_INT, GPIO.IN)
        GPIO.add_event_detect(TOUCH_INT, GPIO.FALLING,
                              callback=touch_callback, bouncetime=800)


The ``touch_callback()`` function then sets a flag, ``screen_press``, that
gets used elsewhere.  For better responsiveness, the interrupt callback is also
able to invoke ``update_display()`` directly; without that immediate call, one has to
wait (up to the sleep time in ``main``) for a reaction.

(It looks like the RPi.GPIO package makes of use ``pthreads`` to provide
for the asynchronous behavior one would expect of an external interrupt.
Exactly how that works given Python's `GIL <https://wiki.python.org/moin/GlobalInterpreterLock>`_
is beyond my current understanding.  If anyone wants to enlighten me, have
it at.  I nevertheless tried to code everything in a thread-safe fashion.)

Doing more with the touchscreen than just taking an interrupt would
require connecting several additional signals.  The XPT2046 controller
is a SPI device, just like the ILI9341.  Theoretically, one should be
able to have both devices present on the same daisy chain.  The
luma.lcd documentation, though, explicitly notes that it doesn't
support touch, and the C4 only has one hardware SPI interface.  If
others want to be adventurous, though, be sure to let me know the
results!



Prototyping Changes
*******************

The ``kodi_panel_demo.py`` script is essentially identical to the
other executable scripts, except that it takes advantage of
luma.lcd's ability to use pygame as a device emulator.
The demo script thus provides a really convenient way of prototyping layout
decisions, font choices, artwork size, etc.  See the header at the
start of that file for how to invoke it.

All of the content within an info display should be adjustable via
the variables in ``setup.toml``.

Here are some examples from the emulator, which also serve to show several
of kodi_panel's available "modes":

.. image:: https://raw.github.com/mattblovell/kodi_panel/master/extras/emulator_status.PNG

.. image:: https://raw.github.com/mattblovell/kodi_panel/master/extras/emulator_default.PNG

.. image:: https://raw.github.com/mattblovell/kodi_panel/master/extras/emulator_full_prog.PNG


When in "demo mode", the main update loop does have code to use
keypresses as emulated touchscreen presses.  The pygame key state is
only sampled at the end of the update process, however, so one must
hold a key and *wait* for that to occur.  The actual T_IRQ
responsiveness ends up being far better, but this does at least give
the emulator the ability to cycle through the display modes and show
the status screen.


Case
****

I adapted a 3D-printable "case" design to fit the 3.2-inch screen.  The 
`design files <https://www.thingiverse.com/thing:4627423>`_ are available on Thingiverse.

See the discussion below on IPS panels for another case option.  Here are two photos of the first case:

.. image:: https://raw.github.com/mattblovell/kodi_panel/master/extras/assembled_case1.jpg

.. image:: https://raw.github.com/mattblovell/kodi_panel/master/extras/assembled_case2.jpg




LCD Brightness / PWM
********************

An LCD panel in a darkened room can be *very* bright. That was one of my
reasons for focusing initially on just a music now-playing screen. All of the
displays I've purchased require PWM (Pulse Width Modulation) for control over
backlight brightness. (The Waveshare panels have fairly straightforward rework
-- moving a resistor -- that gives one PWM control via one of the connector
pins.)

There is code present within luma.lcd to permit for PWM control of the
backlight, using RPi.GPIO. Unfortunately, as of late 2020, RPi.GPIO uses
software to control the PWM on (by default) GPIO18 / Physical Pin 12. Since
exact scheduling cannot be guaranteed with pthreads on Linux, the screen
brightness ends up with a flicker.

The same is true for RPi.GPIO-Odroid, although changes are underway to
enable hardware PWM for it on the N2 and C4 boards.

If you examine ``kodi_panel_fb.py``, there is code present for using
hardware PWM on an RPi.  That code depends upon first loading a device
driver that provides for PWM.  On an RPi 3, this can be accomplished
by adding the following to ``/boot/config.txt``:

::

    # PWM for display
    dtoverlay=pwm-2chan


and then rebooting.  Alternatively, one can invoke 
``sudo dtoverlay /boot/overlays/pwm-2chan.dtbo``.

Following that, a `sysfs <https://en.wikipedia.org/wiki/Sysfs>`_
directory structure should exist under ``/sys/class/pwm``.  The code
in that framebuffer version of kodi_panel makes use of those sysfs
files to control backlight brightness.

   

Further Development
-------------------

Larger Resolutions & IPS Panels
*******************************

I liked the first version of kodi_panel, but the TN (twisted nematic) LCD I used
had a pretty small viewing angle.  One doesn't tend to notice this when sitting at
a desk immediately in front of the display, but it ends up being pretty obvious 
sitting across the living room.  I therefore really wanted to try an IPS display.

I ended up getting both another SPI-connected 3.5-inch IPS display *and* a 4-inch
HDMI IPS panel.  Getting the 3.5-inch ILI9486 display working required extending
luma.lcd, and its authors welcomed the addition.  I got the HDMI display working
thanks to a few additions to luma.core's framebuffer support.

Here's a photo showing the two IPS panels, both from Waveshare.  The 3.5-inch
display is on the left, and the 4-inch display is on the right.

.. image:: https://raw.github.com/mattblovell/kodi_panel/master/extras/dualing_displays.jpg

The displays have resolutions of 480x320 and 800x480, respectively. In order to
support those sizes, as well as the original 320x240, I ended up adding TOML
support for a setup file. The details of creating a luma.lcd display, or
setting up the framebuffer as a device, were also separated from the "draw with
Pillow" portion of the script.

With the slightly larger 4-inch display, a new case was needed.  Those
`new design files <https://www.thingiverse.com/thing:4704093>`_ are also posted on Thingiverse.

Movie Info
**********

With version 0.99, ``kodi_panel_display.py`` has preliminary support for showing
info screens during video playback.  I only have movies on my server, so I don't
have any material with which to test TV episodes.  Audio and video info screens
can be separately enabled or disabled, per variables in your ``setup.toml`` file.

See the ``example_setup_800x480.toml`` file for the data structures (more Python
dictionaries) that must be set up for video info screens.  The default screen
presently implemented includes the movie poster, progress bar, elapsed time, 
title, genre, year, and rating.

Some example screens from the emulator mode:

.. image:: https://raw.github.com/mattblovell/kodi_panel/master/extras/movie_example1.PNG
  :width: 480

.. image:: https://raw.github.com/mattblovell/kodi_panel/master/extras/movie_example2.PNG
  :width: 480

One must declare what video info screens exist, via ``VLAYOUT_NAMES`` and then
populate screen contents in the ``V_LAYOUT`` dictionary.  These data structures
are directly analogous to ``ALAYOUT_NAMES`` and ``A_LAYOUT``.   See the
JSON-RPC call involving ``VideoPlayer`` fields in ``update_display()`` to
see what fields are available for displaying.

Slideshow Screens
*****************

The most recent versions of kodi_panel also have support for showing screens
during photo slideshows.  Just as with audio or video, one has to setup at
least one layout, defining ``SLAYOUT_NAMES`` and an ``S_LAYOUT`` dictionary.



License
-------
The MIT License (MIT)

Copyright (c) 2020-21 Matthew Lovell and contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
