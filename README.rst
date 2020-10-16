kodi_panel
==========

Kodi_panel is a standalone Python 3 script that provides an
information front panel for Kodi via an attached LCD display.  The LCD
is handled entirely by `luma.core <https://github.com/rm-hull/luma.core/>`_
and `luma.lcd <https://github.com/rm-hull/luma.lcd/>`_, which in turn
depend upon `pillow <https://python-pillow.org/>`_ and `RPi.GPIO
<https://pypi.org/project/RPi.GPIO/>`_.  Information and album cover artwork
is retrieved from Kodi using
`JSON-RPC <https://kodi.wiki/view/JSON-RPC_API>`_.

The script is generally intended to run on the same SBC (single-board
computer) on which Kodi itself is running.  That's not really
necessary, though, provided one is willing to let the JSON-RPC calls
occur over the network.

For Raspberry PI boards, RPi.GPIO obviously works as-is.  For Odroid
boards, one must instead make use of
`RPi.GPIO-Odroid <https://github.com/awesometic/RPi.GPIO-Odroid>`_.

.. image:: https://raw.github.com/mattblovell/kodi_panel/master/images/working_lcd.jpg

**Disclaimer:** This project is *not* directly associated with either
`Kodi <https://kodi.tv/>`_ or
`CoreELEC <https://coreelec.org/>`_.

The general approach taken by this project, running separately from Kodi
itself and retrieving all relevant state via JSON-RPC, has been used by other
projects.  The main advantage of *not* being a Kodi addon is that, at least
with Kodi Leia, one is no longer restricted to Python 2.  Being a standalone
script also means that one can have a separate SBC driving a "Now Playing"
screen anywhere one would like!  

The ``kodi_panel.py`` script is also fairly short.  If you are
familiar with reading and writing Python, and making use of the pillow
image library, it should be straightforward to modify it to your taste
or needs.  Using Python also lets one experiment with and inspect the
results of the JSON-RPC calls to Kodi quite easily.  The Kodi documentation
on
`JSON-RPC <https://kodi.wiki/view/JSON-RPC_API>`_ and
`InfoLabels <https://kodi.wiki/view/InfoLabels>`_
should give you a complete picture of what information is available.
(One can also change Kodi's state using JSON-RPC, something I don't even
attempt here!)


Installation
------------

I only have direct access to a Raspberry Pi Model B and an Odroid C4.
As others try additional SBCs, please feel free to suggest additions or
changes to this documentation.

The first step is really to get your display of choice connected
and working.  A prequisite is thus understanding the GPIO pinout of
your SBC.  Be aware the GPIO pins have both *physical* numbers and
numbers or names as assigned by whatever software one happens to be using
to control and access them.  Since luma.lcd makes use of RPi.GPIO,
the numbers you'll see in ``kodi_panel.py`` all correspond to
RPi.GPIO's logical numbering scheme.  Fortunately, that scheme is
well-documented all over the web, for instance at this
`SparkFun GPIO <https://learn.sparkfun.com/tutorials/raspberry-gpio/gpio-pinout>`_ page.

On another note, for *all* the display modules that I tried before settling
on the ili9341-based LCDs, I only ever tried using 3.3V for Vcc.  This
avoided having to worry about `level shifters <https://www.adafruit.com/product/1875>`_.
Be careful wiring up your SBC; if you're not familiar with them
generally, see the warnings documented on the RPi
`GPIO usage <https://www.raspberrypi.org/documentation/usage/gpio/>`_ page.



Raspberry Pi
************

For Raspberry Pi, follow the
`installation directions <https://luma-lcd.readthedocs.io/en/latest/>`_ from
luma.lcd to get your display working.  Luma's directions are thorough
and provide suggested wiring for a number of displays.  You can make
use of `luma.examples <https://github.com/rm-hull/luma.examples>`_
to test and exercise the display.  The installation directions assume
you are running a fairly complete Linux distribution, such as
`Raspberry Pi OS <https://www.raspberrypi.org/downloads/raspberry-pi-os/>`_.

Once you have the luma.examples working, you're really about done!
Install Kodi as well, and get it working as desired.  If kodi_panel is
to run on the same SBC as is hosting the display, then no immediate
editing of ``kodi_panel.py`` should be needed.  Otherwise, you will need
to at least specify the correct IP address to use for kodi_panel's ``base_url``
variable.  After that, try starting kodi_panel by
changing directory to ``kodi_panel`` and invoking

::

  python3 kodi_panel.py


Ideally, you'll then see the start of kodi_panel's log-style standard output:

::

  2020-10-16 09:29:54.233730 Starting
  2020-10-16 09:29:54.234313 Setting up touchscreen interrupt
  2020-10-16 09:29:54.293762 Connected with Kodi.  Entering update_display() loop.



Odroid Boards
*************

For Odroid boards, if you're interested in learning the (short) development
history of kodi_panel, you can read through these two discussions in
CoreELEC's forums:

- `Graphical front panel display <https://discourse.coreelec.org/t/graphical-front-panel-display/12932>`_
- `RPi-GPIO-Odroid & Python Pillow <https://discourse.coreelec.org/t/rpi-gpio-odroid-python-pillow/13088>`_

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

The immediate goal is still the same -- get luma.lcd installed and talking
to your display.  There are just a few more steps necessary to achieve that
goal than if you had armbian or Debian installed.  (I'm not going to describe
how to secure-shell (ssh) into your CoreELEC SBC; you should
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

4. Install the entware-compiled version of pillow:

   ::

     opkg install python3-pillow

5. You should then be able install luma.lcd in basically the usual fashion:

   ::

     pip3 install luma.lcd

Assuming the above is all successful, you should now be able to
run any of the demonstrations from luma.examples.  If Kodi is up
and running (it is CoreELEC, after all), one then then cd into
kodi_panel's directory and invoke

::

  /opt/bin/python3 kodi_panel.py

Now, try playing something!

To have kodi_panel start up when the Odroid is powered-on, I take advantage
of Kodi's ``autostart.sh`` mechanism.  An example file is provided as part
of kodi_panel.

I have only tried the above on an Odroid C4.  If others want to inform me of their
attempts and what instruction changes need to be captured, please let me know.


Touch Interrupt
***************

For the 3.2-inch ILI9341-based board that I tried, the touch
controller (XPT2046) was sufficiently active following power-up that
T_IRQ, the touch interrupt, was working!  It was not necessary to send
any command to the controller or even connect T_CLK.  The T_IRQ signal
is by default pulled up to Vcc by an internal resistor and gets pulled
down to ground when the screen it pressed.

This was all I needed to give it a try!

All that was necessary was to find a GPIO pin that was free to use an
an input.  For my Odroid C4 board, that turned out to be GPIO19, otherwise
known as Pin Number 35.

The following block of code in ``kodi_panel.py`` is qualified by a USE_INT
conditional that defaults to True:

::

    # setup T_IRQ as a GPIO interrupt, if enabled
    if USE_TOUCH:
        print(datetime.now(), "Setting up touchscreen interrupt")
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(TOUCH_INT, GPIO.IN)
        GPIO.add_event_detect(TOUCH_INT, GPIO.FALLING,
                              callback=touch_callback, bouncetime=800)


The ``touch_callback()`` function then sets a flag (``screen_press``) that
gets used elsewhere.  For better responsive, the interrupt callback is also
able to invoke ``update_display()``; without that immediate call, one has to
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
-------------------

The ``luma_demo.py`` script is almost a duplicate of ``kodi_panel.py``.
Taking advantage of luma.lcd's ability to use pygame as a device
emulator, it provides a really convenient way of prototyping layout
decisions, font choices, artwork size, etc.  See the header at the
start of that file for how to invoke it.

Here's an example of ``luma_demo.py`` running from earlier in kodi_panel's development:

.. image:: https://raw.github.com/mattblovell/kodi_panel/master/images/emulator_example.png


In the main loop for ``luma_demo.py`` I did recently add code to use
keypresses as emulated touchscreen presses.  The pygame key state is
only sampled at the end of the update process, however, so one must
hold a key and *wait* for that to occur.  The actual T_IRQ
responsiveness ends up being far better, but this does at least give
the emulator the ability to cycle through the display modes and show
the status screen.
   

License
-------
The MIT License (MIT)

Copyright (c) 2020 Matthew Lovell

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
