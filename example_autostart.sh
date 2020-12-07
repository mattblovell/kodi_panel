#!/bin/sh

/opt/etc/init.d/rc.unslung start

sleep 5

(
cd ~/projects/kodi_panel
nohup /opt/bin/python3 -u kodi_panel_ili9341.py > ~/kodi_panel.log &
) &

