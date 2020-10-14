kodi_panel
==========

Kodi_panel is a standalone Python 3 script that provides an
information front panel for Kodi via an attached LCD display.  The LCD
is handled entirely by `luma.core <https://github.com/rm-hull/luma.oled/>`
and `luma.lcd <https://github.com/rm-hull/luma.lcd/>`, which in turn
depend upon `pillow <https://python-pillow.org/>` and `RPi.GPIO
<https://pythonhosted.org/RPIO/>`.

The script is generally intended to run on the same SBC (single-board
computer) on which Kodi itself is running.  That's not really
necessary, though, provided one is willing to let the JSON-RPC calls
to Kodi occur over the network.

For Raspberry PI boards, RPi.GPIO obviously works as-is.  For Odroid
boards, one must instead make use `RPi.GPIO-Odroid
<https://github.com/awesometic/RPi.GPIO-Odroid>`.


Installation
------------

For Raspberry Pi, first follow the
`installation directions <https://luma-lcd.readthedocs.io/en/latest/>` for
luma.lcd and get your display working (using luma's examples).

For Odroid boards, more details are to be documented.  For now, please
see these two discussions in CoreELEC's forums:
- `Graphical front panel display <https://discourse.coreelec.org/t/graphical-front-panel-display/12932>`
- `RPi-GPIO-Odroid & Python Pillow <https://discourse.coreelec.org/t/rpi-gpio-odroid-python-pillow/13088>`

The second thread provides installation steps for CoreELEC, making use
`Entware <https://github.com/Entware/Entware/wiki>`.



Prototyping Changes
-------------------

The `luma_demo.py` script is almost a duplicate of `kodi_panel.py`.
Taking advantage of luma.lcd's ability to use pygame as a device
emulator, it provides a really convenient way of prototyping layout
decisions, font choices, artwork size, etc.  See the header at the
start of that file for how to invoke it.



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
