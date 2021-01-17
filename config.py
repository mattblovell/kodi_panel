#
# MIT License -- see LICENSE.rst for details
# Copyright (c) 2020-21 Matthew Lovell and contributors
#
# ----------------------------------------------------------------------------

# TOML file is used for settings
#
#    See format reference at https://toml.io/en/
#
#    TOML is context sensitive, so the order of the entries in the
#    file (particularly the arrays of tables) DOES matter,
#    unfortunately.
#
#    One can use the environment variable
#
#      KODI_PANEL_SETUP
#
#    to specify a name different than the default "setup.toml".
#    
import toml
import os
import sys
    
setup_file = os.getenv('KODI_PANEL_SETUP') or "setup.toml"
# print("Loading kodi_panel configuration from file:", setup_file)

try:
    settings = toml.load(setup_file)
except Exception as e:
    print("Unexpected error trying to load/parse setup file! \n", e)
    sys.exit(1)
