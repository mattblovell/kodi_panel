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
