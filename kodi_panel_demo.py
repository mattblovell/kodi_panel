#
# MIT License -- see LICENSE.rst for details
# Copyright (c) 2020-21 Matthew Lovell and contributors
#
# ----------------------------------------------------------------------------
#
# This script, via luma.core's ability to use pygame as a display
# emulator, creates a window on X that shows kodi_panel.  This demo
# version is intended to aid in development since one can prototype
# layout choices, play with different fonts, change positions of
# elements, etc.
#
# As currently written, the script (and font and image subdirectories)
# must be copied to the
#
#   luma.examples/examples
#
# directory (after cloning it from github) and executed via a command
# like the following:
#
#   python kodi_panel_demo.py --display pygame --width 320 --height 240 --scale 1
#
# Screen touches are somewhat emulated within the main() update loop
# of kodi_panel_display by checking for a pressed key via pygame's
# state.  The state is polled only once per update loop, though, so
# one must hold the button for a bit.
#
# Since this script is usually running on a desktop machine, you MUST
# also specify the correct base_url via the settings TOML file.
#
# ----------------------------------------------------------------------------

from demo_opts import get_device      # from luma.examples (REQUIRED FOR EMULATION)

# kodi_panel modules
import config
import kodi_panel_display

# ----------------------------------------------------------------------------

# Handle to pygame emulator
device = get_device()

if __name__ == "__main__":
    kodi_panel_display.DEMO_MODE = True
    try:
        kodi_panel_display.main(device)
    except KeyboardInterrupt:
        kodi_panel_display.shutdown()
        pass
