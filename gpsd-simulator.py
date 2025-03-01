#!/usr/bin/env python
# -*- coding: utf-8 -*-

###################################################
### https://github.com/cLxJaguar/gpsd-simulator ###
###################################################

from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *
from PyQt5.QtNetwork import *

import os, sys, time, math, socket, re, pyqtgraph, pygame.joystick, geopy.distance
from datetime import datetime

class Server(QObject):
	statusUpdate = pyqtSignal()

	def __init__(self, port=2947, portAutoIncrement=True):
		QWidget.__init__(self)
		self.connections = []
		self.filename = None
		self.server = QTcpServer()
		tries = 0
		while True:
			tries+=1
			isListening = self.server.listen(QHostAddress("127.0.0.1"), port=port)
			if isListening:
				break
			if not portAutoIncrement:
				raise Exception("Not able to listen to TCP port %d" % port)
			port+=1
			if tries>100:
				print(port)
				raise Exception("Server failed to listen to TCP ports")

		self.server.newConnection.connect(self.onNewConnection)
		self.server.acceptError.connect(self.onAcceptError)

	def getLocalHostPort(self):
		address = self.server.serverAddress().toString()
		port = self.server.serverPort()
		return address, port

	def getServerStatus(self):
		address = self.server.serverAddress()
		port = self.server.serverPort()
		text = "Listening to %s:%d" % (address.toString(), port)
		if len(self.connections):
			text+='\n\nConnected clients:'
			for c in self.connections:
				text+= "\n%s:%d" % (c.peerAddress().toString(), c.peerPort())
		return text

	def sendCoordsToClients(self, lat, lon, **kwargs):
		# {"class":"TPV","time":"%s","ept":0.005, "lat":%s,"lon":%s,"alt":1327.689, "epx":15.319,"epy":17.054,"epv":124.484,"track":%f, "speed":9.091,"climb":-20.085,"eps":34.11,"mode":3}\n
		# {"class":"TPV","time":"%s","lat":%s,"lon":%s,"track":%f,"mode":3}\n

		if 'time' in kwargs:
			time = datetime.utcfromtimestamp(kwargs['time']).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
		else:
			time = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")

		msg = '{"class":"TPV","time":"%s","lat":%.8f,"lon":%.8f' % (time, lat, lon)

		if 'heading' in kwargs:
			msg+=',"track":%.2f' % kwargs['heading']
		else:
			msg+=',"track":0.0'

		if 'altitude' in kwargs:
			msg+=',"altHAE":%.3f' % kwargs['altitude']
		if 'speed' in kwargs:
			msg+=',"speed":%g' % kwargs['speed']
		if 'climb' in kwargs:
			msg+=',"climb":%g' % kwargs['climb']

		if 'mode' in kwargs:
			msg+=',"mode":%d}\n' % (kwargs['mode'])
		else:
			msg+=',"mode":3}\n'

		msg = bytes(msg, encoding='ascii')
		print(msg)

		for c in self.connections:
			c.write(msg)

	def onNewConnection(self):
		connection = self.server.nextPendingConnection()
		connection.write(b'{"class":"VERSION","release":"2.93","rev":"GPSd simulator", "proto_major":3,"proto_minor":2}\n')
		print("New connection from %s:%d" % (connection.peerAddress().toString(), connection.peerPort()))

		connection.readyRead.connect(self.processMessage)
		connection.disconnected.connect(self.onDisconnected)

		self.connections.append(connection)
		self.statusUpdate.emit()

	def onDisconnected(self):
		connection = self.sender()
		print("Disconnection of %s:%d" % (connection.peerAddress().toString(), connection.peerPort()))
		self.connections.remove(connection)
		self.statusUpdate.emit()

	def onAcceptError(self, x):
		print("onAcceptError:", x)

	def processMessage(self):
		connection = self.sender()
		msg = connection.read(102400)
		print("%s:%d: %s" % (connection.peerAddress().toString(), connection.peerPort(), msg.decode('utf-8').strip()))

	def close(self):
		for c in self.connections:
			c.close()

class HWJoystick(QObject):
	os.environ['SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS'] = '1'
	pygame.init()
	pygame.mixer.quit() # stop heavy cpu consumption

	joystickMoved = pyqtSignal(float, float)
	buttonsStatesUpdated = pyqtSignal(list)
	# https://www.pygame.org/docs/ref/joystick.html
	def __init__(self):
		QObject.__init__(self)
		pygame.joystick.init()
		if pygame.joystick.get_count() > 0:
			self.joystick = pygame.joystick.Joystick(0)
			print("Using %s" % (self.joystick.get_name()))
			self.joystick.init()
		else:
			self.joystick = None

		self.thread = QThread()
		self.thread.setObjectName("Joystick Thread")
		self.moveToThread(self.thread)
		self.thread.started.connect(self.worker)
		self.thread.start()

	def stop(self):
		try:
			pygame.event.post(pygame.event.Event(pygame.QUIT))
		except Exception as e:
			print("Pygame complaining:", e)
		self.thread.quit()

	def worker(self):
		while True:
			event = pygame.event.wait()

			if event.type == pygame.QUIT:
				pygame.quit()
				return

			if event.type == pygame.AUDIODEVICEADDED:
				continue

			if event.type == pygame.JOYDEVICEREMOVED:
				self.joystickMoved.emit(0.0, 0.0)
				self.joystick = None

			elif event.type == pygame.JOYDEVICEADDED:
				if self.joystick is None:
					self.joystick = pygame.joystick.Joystick(event.device_index)
					print("Using %s" % (self.joystick.get_name()))
					self.joystick.init()

			if self.joystick is None:
				continue

			# Possible joystick actions: JOYAXISMOTION, JOYBALLMOTION, JOYBUTTONDOWN, JOYBUTTONUP, JOYHATMOTION

			if event.type == pygame.JOYAXISMOTION:
				self.joystickMoved.emit(self.joystick.get_axis(0), -self.joystick.get_axis(1))

			elif event.type in (pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP):

				buttons = []
				for i in range(self.joystick.get_numbuttons()):
					buttons.append(self.joystick.get_button(i))
				self.buttonsStatesUpdated.emit(buttons)

			else:
				print(event)


class GUI(QWidget):
	class DateTimeLineEdit(QLineEdit):
		def __init__(self, text=""):
			QLineEdit.__init__(self, text)
			self.setReadOnly(True)
			self.setStyleSheet('color: gray;')

		def now(self):
			self.time = time.time()
			self.datetime = datetime.utcfromtimestamp(self.time)
			self.setText(self.datetime.strftime("%Y-%m-%d %H:%M:%S.%f"))
			self.setStyleSheet('')

		def set(self, ts):
			self.time = ts
			self.datetime = datetime.utcfromtimestamp(self.time)
			self.setText(self.datetime.strftime("%Y-%m-%d %H:%M:%S.%f"))
			self.setStyleSheet('')

	class CoordsLineEdit(QLineEdit):
		coordsChanged = pyqtSignal(float, float)

		def __init__(self, text="0 0"):
			QLineEdit.__init__(self, text)
			self.lat, self.lon = [float('nan')]*2
			self.textChanged.connect(self._textChanged)
			self._textChanged(self.text())

		def _textChanged(self, text):
			try:
				lat, lon = map(float, text.split())
				if lat > 90 or lat < -90 or lon > 180 or lon < -180:
					raise ValueError("Invalid coordinates!")

				self.oldLat, self.oldLon = self.lat, self.lon
				self.lat, self.lon = lat, lon
				self.coordsChanged.emit(self.lat, self.lon)
				self.setStyleSheet('')
			except:
				try:
					match = re.search("([\-0-9]+)[.,]([0-9]+)[,+ ] ?([\-0-9]+)[.,]([0-9]+)", text)
					if match:
						self.setText("%s.%s %s.%s" % (match.group(1), match.group(2), match.group(3), match.group(4)))
						return

				except:
					pass

				self.setStyleSheet('background: #ffa0a0;')

		def move(self, lat, lon, delta=False):
			self.oldLat, self.oldLon = self.lat, self.lon
			if delta:
				self.lat+= lat
				self.lon+= lon
			else:
				self.lat, self.lon = lat, lon

			if self.lat > 90:
				self.lat = 90
			elif self.lat < -90:
				self.lat = -90
			if self.lon < -180:
				self.lon+=360
			elif self.lon > 180:
				self.lon-=360

			self.blockSignals(True)
			self.setText("%.6f %.6f" % (self.lat, self.lon))
			self.blockSignals(False)

		def getHeading(self):
			dLon = self.lon - self.oldLon
			y = math.sin(math.radians(dLon)) * math.cos(math.radians(self.lat))
			x = math.cos(math.radians(self.oldLat))*math.sin(math.radians(self.lat)) - math.sin(math.radians(self.oldLat))*math.cos(math.radians(self.lat))*math.cos(math.radians(dLon))
			heading = math.degrees(math.atan2(y, x))
			if heading < 0: heading+= 360
			return heading

	class HeadingSpinBox(QDoubleSpinBox):
		headingChanged = pyqtSignal(float)
		def __init__(self):
			QDoubleSpinBox.__init__(self)
			self.valueChanged.connect(self._valueChanged)
			self.setValue(0)

		def event(self, e):
			if type(e) is QWheelEvent:
				QDoubleSpinBox.setValue(self, round(self.value()))
			return QDoubleSpinBox.event(self, e)

		def _valueChanged(self, value):
			if value >= 360:
				value-=360
				self.setValue(value)
			elif value < 0:
				value%=360
				self.setValue(value)
			else:
				self.realValue = value

			self.headingChanged.emit(value)

		def setValue(self, value, delta=False):
			if delta:
				self.realValue+= value
			else:
				self.realValue = value

			if self.realValue >= 360:
				self.realValue-=360
			elif self.realValue < 0:
				self.realValue%=360

			self.blockSignals(True)
			QDoubleSpinBox.setValue(self, self.realValue)
			self.blockSignals(False)
			return self.realValue

		def value(self):
			return self.realValue


	class SimulationTab(QWidget):
		tabTitle = "Simulate"

		class JoystickButton(pyqtgraph.JoystickButton):
			def __init__(self):
				pyqtgraph.JoystickButton.__init__(self)
				self.setFixedWidth(100)
				self.setFixedHeight(100)

			def setPosition(self, x, y):
				xy = [x, y]
				w2 = self.width() / 2
				h2 = self.height() / 2
				self.spotPos = QPoint(
					int(w2 * (1 + xy[0])),
					int(h2 * (1 - xy[1]))
				)
				self.update()

		def __init__(self, gui):
			QWidget.__init__(self)
			self.gui = gui
			l = QGridLayout(self)

			self.jb = self.JoystickButton()
			self.jb.sigStateChanged.connect(self.jbMoved)
			l.addWidget(self.jb, 0, 0, 2, 1)

			self.maxSpeedSb = QDoubleSpinBox()
			self.maxSpeedSb.setMaximum(10000000)
			self.maxSpeedSb.setValue(10)
			self.maxSpeedSb.setSuffix(' km/h')
			l.addWidget(QLabel("Max Speed"), 0, 1)
			l.addWidget(self.maxSpeedSb, 0, 2)

			gb = QGroupBox('Mode')
			l2 = QHBoxLayout(gb)
			self.mode1 = QRadioButton("dLat/dLon", checked=True)
			l2.addWidget(self.mode1)
			self.mode2 = QRadioButton("Speed/Heading")
			l2.addWidget(self.mode2)
			l.addWidget(gb, 1, 1, 1, 2)

			l.setRowStretch(2, 1)

			self.joy_x, self.joy_y = 0, 0
			self.joystick = HWJoystick()
			self.joystick.joystickMoved.connect(self.hwJoyMoved)

			self.updatePositionTimer = QTimer()
			self.updatePositionTimer.timeout.connect(self.updatePosition)

		def hwJoyMoved(self, x, y):
			if -0.01<x<0.01: x=0
			else: x**=3
			if -0.01<y<0.01: y=0
			else: y**=3

			self.jb.setPosition(x, y)
			self.jbMoved(None, (x, y))

		def jbMoved(self, b, xy):
			self.joy_x, self.joy_y = xy
			if self.joy_x or self.joy_y:
				if not self.updatePositionTimer.isActive():
					self.updatePositionTimer.start(100)
			else:
				if self.updatePositionTimer.isActive():
					self.updatePositionTimer.stop()

		def updatePosition(self):
			if self.mode1.isChecked():
				dlat = self.maxSpeedSb.value() * self.joy_y * 2.5e-07
				dlon = self.maxSpeedSb.value() * self.joy_x * 2.5e-07 / math.cos(math.radians(self.gui.coords.lat))
				if   dlon >  90: dlon =  90
				elif dlon < -90: dlon = -90

				self.gui.dateTime.now()
				self.gui.coords.move(dlat, dlon, delta=True)

			elif self.mode2.isChecked():
				if -0.1 < self.joy_x < 0.1:
					hdg = self.gui.heading.value()
				else:
					dhdg = self.joy_x * (20 if self.joy_y < 0.5 else 3)
					hdg = self.gui.heading.setValue(dhdg, delta=True)
					if self.gui.headingFromCoordsChange.isChecked():
						self.gui.headingFromCoordsChange.setChecked(False)

				lat, lon = self.gui.coords.lat, self.gui.coords.lon
				d = self.maxSpeedSb.value() * self.joy_y / 36000
				p = geopy.distance.distance().destination((lat, lon), bearing=hdg, distance=d)
				self.gui.dateTime.now()
				self.gui.coords.move(p.latitude, p.longitude)

			self.gui.update()

		def closeEvent(self, event):
			self.joystick.stop()


	def __init__(self):
		QWidget.__init__(self)
		self.initUI()

		try:
			self.server = Server()
			host, port = self.server.getLocalHostPort()
			self.setWindowTitle("GPSd on %s:%d" % (host, port))
		except Exception as e:
			x = QMessageBox(None, "Server Error", str(e), None)
			print(x)
			exit(1)


	def initUI(self):
		mainvbox = QVBoxLayout(self)

		l = QGridLayout()
		mainvbox.addLayout(l)

		self.coords = self.CoordsLineEdit("48.858252 2.294502")
		self.coords.coordsChanged.connect(self.update)
		l.addWidget(QLabel("Coordinates"), l.rowCount(), 1)
		l.addWidget(self.coords, l.rowCount()-1, 2, 1, 2)

		self.dateTime = self.DateTimeLineEdit()
		l.addWidget(QLabel("Time"), l.rowCount(), 1)
		l.addWidget(self.dateTime, l.rowCount()-1, 2, 1, 2)

		self.heading = self.HeadingSpinBox()
		self.heading.setRange(-360, 720)
		self.heading.headingChanged.connect(self.update)
		l.addWidget(QLabel("Heading"), l.rowCount(), 1)
		l.addWidget(self.heading, l.rowCount()-1, 2)
		self.headingFromCoordsChange = QCheckBox("From coords")
		self.headingFromCoordsChange.setChecked(True)
		l.addWidget(self.headingFromCoordsChange, l.rowCount()-1, 3)

		self.altitude = QDoubleSpinBox()
		self.altitude.setRange(-1000, 100000)
		l.addWidget(QLabel("Altitude"), l.rowCount(), 1)
		l.addWidget(self.altitude, l.rowCount()-1, 2)

		self.modeTab = QTabWidget()
		for t in [self.SimulationTab]:
			self.modeTab.addTab(t(self), t.tabTitle)
		mainvbox.addWidget(self.modeTab)

		self.setWindowTitle(u'GPSd Simulator')
		self.show()

	def update(self):
		if self.headingFromCoordsChange.isChecked():
			self.heading.setValue(self.coords.getHeading())
		self.server.sendCoordsToClients(self.coords.lat, self.coords.lon, time=self.dateTime.time, altitude=self.altitude.value(), heading=self.heading.value())

	def closeEvent(self, event):
		for i in range(self.modeTab.count()):
			self.modeTab.widget(i).close()

def main():
	app = QApplication(sys.argv)
	m1 = GUI()
	ret = app.exec_()
	sys.exit(ret)

if __name__ == '__main__':
	main()
