# gpsd-simulator

I needed to pinpoint moving objects positions in [Viking](https://sourceforge.net/projects/viking/), so i made this, as that program is supporting [GPSd](https://gpsd.io/) protocol to (usually) show the current live location. My code mimic a tiny fraction of the protocol, but is enough to permit to show moving things. There is possible to run several instances to show several points in the same time, the used port is simply incremented.

* Simulation mode (with joystick or mouse)

https://github.com/user-attachments/assets/b09aa5d6-195a-4d6d-8fb2-9ec4fc4772e7

* NMEA 0183 (Serial GPS bridge)

It can parse $GPRMC messages from an external GPS.

Type this and your bluetooth device will be available as /dev/rfcomm0:

```
$ sudo rfcomm bind /dev/rfcomm0 xx:xx:xx:xx:xx:xx
```

* Data file

Reading CSV data files
