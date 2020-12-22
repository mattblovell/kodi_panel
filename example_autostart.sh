#!/bin/sh

#
# Example Kodi autostart file for kodi_panel.  Edit
# as appropriate for your insallation.
#

# Entware startup
/opt/etc/init.d/rc.unslung start

sleep 5

(
cd ~/projects/kodi_panel
nohup /opt/bin/python3 -u kodi_panel_ili9341.py > ~/kodi_panel.log &
) &

