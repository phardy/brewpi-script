# Copyright 2012 BrewPi
# This file is part of BrewPi.

# BrewPi is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# BrewPi is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with BrewPi.  If not, see <http://www.gnu.org/licenses/>.

import sys
# Check needed software dependencies to nudge users to fix their setup
if sys.version_info < (2, 7):
	print "Sorry, requires Python 2.7."
	sys.exit(1)

# standard libraries
import time
import os
import getopt
import BrewPiUtil as util
import csv

# load non standard packages, exit when they are not installed
try:
	from configobj import ConfigObj
except ImportError:
	print "This script requires ConfigObj to run, please install it with 'sudo apt-get install python-configobj"
	sys.exit(1)

try:
	from reportlab.graphics.shapes import Drawing
	from reportlab.graphics.charts.lineplots import ScatterPlot, GridLinePlot
	from reportlab.graphics.charts.axes import NormalDateXValueAxis
	from reportlab.pdfgen import canvas
	from reportlab.graphics import renderPDF
except ImportError:
	print "This script requires reportlab to run, please install it with 'sudo apt-get install python-reportlab"
	sys.exit(1)

# Read in command line arguments
try:
	opts, args = getopt.getopt(sys.argv[1:], "hc:i:", ['help', 'config=', 'input='])
except getopt.GetoptError:
	print "Available Options: --help, --config <path to config file>, --input <path to csv file>"
	sys.exit()

configFile = None
inputFile = None

for o, a in opts:
	# print help message for command line options
	if o in ('-h', '--help'):
		print "\n Available command line options: "
		print "--help: print this help message"
		print "--config <path to config file>: specify a config file to use. Used for the temperature format." \
		      "Reverts to default location when omitted"
		print "--input <path to csv file>: specify which csv file to analyze." \
		      "Reverts to current beer when omitted"
		exit()
	# supply a config file
	if o in ('-c', '--config'):
		configFile = os.path.abspath(a)
		if not os.path.exists(configFile):
			sys.exit('ERROR: Config file "%s" was not found!' % configFile)
	if o in ('-i', '--input'):
		inputFile = os.path.abspath(a)
		if not os.path.exists(inputFile):
			sys.exit('ERROR: Input file "%s" was not found!' % configFile)

if not configFile:
	print >> sys.stderr, ("Using default config path <script dir>/settings/config.cfg, " +
                          "to override use: %s --config <config file full path>" % sys.argv[0])
	configFile = util.scriptPath() + '/settings/config.cfg'

config = util.readCfgWithDefaults(configFile)

dataPath = util.addSlash(util.addSlash(config['scriptPath']) + 'data/' + config['beerName'])

if not inputFile:
	print >> sys.stderr, ("Using current beer as input, \
	                       to override use: %s --input <path to csv file>" % sys.argv[0])
	inputFile = (dataPath + config['beerName'] + '.csv')

print >> sys.stderr, "\n\n Analyzing CSV file '" + inputFile + "'"

inputFileObject = open(inputFile)

csvReader = csv.reader(	open(inputFile), delimiter=';', quoting=csv.QUOTE_ALL)
csvReader.next()  # discard the first row, which is the table header

now = time.mktime(time.localtime())  # get current time in seconds since epoch

state = None
statePrev = None
posPeak = None
negPeak = None
date = None
datePrev = None

dateString = None
beerTemp = None
beerSet = None
beerAnn = None
fridgeTemp = None
fridgeSet = None
fridgeAnn = None
state = None
roomTemp = None

timeTotal = 0
idleTimeTotal = 0
offTimeTotal = 0
doorOpenTimeTotal = 0
heatingTimeTotal = 0
coolingTimeTotal = 0
waitingToCoolTimeTotal = 0
waitingToHeatTimeTotal = 0
waitingForPeakDetectTimeTotal = 0
coolingMinTimeTimeTotal = 0
heatingMinTimeTimeTotal = 0

getNegPeak = False
getPosPeak = False
negPeak = None
posPeak = None
settingAtCoolOff = None
settingAtHeatOff = None
tempAtCoolOff = None
tempAtHeatOff = None
negOvershootEstimate = None
posOvershootEstimate = None
coolStart = None
heatStart = None
idleStart = None
coolTime = None
heatTime = None
maxCoolTimeForEstimate = 5000

startTimeString = "2013-08-27 10:16:13"
stopTimeString = "2013-09-10 00:00:00"
startTime = time.mktime(time.strptime(startTimeString, "%Y-%m-%d %H:%M:%S"))
stopTime = time.mktime(time.strptime(stopTimeString, "%Y-%m-%d %H:%M:%S"))

# CSV format: Date; BeerTemp; BeerSet; BeerAnn; FridgeTemp; FridgeSet; FridgeAnn; State; RoomTemp;

idleStates = [0, 2, 5, 6, 7]
coolStates = [4,8]

coolDataPoints = []

def updateTemp(temp, inputString):
	try:
		return float(inputString)
	except ValueError:
		return temp


for row in csvReader:
	statePrev = state
	datePrev = date

	dateString = row[0]
	beerTemp = updateTemp(beerTemp, row[1])
	beerSet = updateTemp(beerSet, row[2])
	beerAnn = row[3]
	fridgeTemp = updateTemp(fridgeTemp, row[4])
	fridgeSet = updateTemp(fridgeSet, row[5])
	fridgeAnn = row[6]
	state = int(row[7])
	roomTemp = updateTemp(roomTemp, row[8])

	try:
		date = time.mktime(time.strptime(dateString, "%b %d %Y %H:%M:%S"))
	except ValueError:
		print >> sys.stderr, "Could not pass date string: " + dateString
		continue  # skip dates that cannot be parsed

	if not date or not datePrev:
		continue
	if date < startTime:
		continue
	if date > stopTime:
		break
	if date < datePrev or date - datePrev > 600000:  # 5 minutes
		# nonlinearity or gap in dates, probably because restarting script, skip and reset
		getNegPeak = False
		getPosPeak = False
		heatStart = None
		coolStart = None
		continue

	timeDiff = date - datePrev
	timeTotal += timeDiff

	# process state info, use previous state to determine what the state was in this period
	if statePrev == 0:
		idleTimeTotal += timeDiff
	elif statePrev == 1:
		offTimeTotal += timeDiff
	elif statePrev == 2:
		doorOpenTimeTotal += timeDiff
	elif statePrev == 3:
		heatingTimeTotal += timeDiff
	elif statePrev == 4:
		coolingTimeTotal += timeDiff
	elif statePrev == 5:
		waitingToCoolTimeTotal += timeDiff
	elif statePrev == 6:
		waitingToHeatTimeTotal += timeDiff
	elif statePrev == 7:
		waitingForPeakDetectTimeTotal += timeDiff
	elif statePrev == 8:
		coolingMinTimeTimeTotal += timeDiff
	elif statePrev == 9:
		heatingMinTimeTimeTotal += timeDiff

	if state in idleStates:  # in idle state
		if getNegPeak:
			if fridgeTemp < negPeak or not negPeak:
				negPeak = fridgeTemp
	if statePrev in idleStates and state not in idleStates:  # move out of idle
		if getNegPeak:
			overshoot = tempAtCoolOff - negPeak
			peakTime = date
			print dateString
			print "Negative peak: " + str(negPeak) + " Estimated: " + str(settingAtCoolOff)
			print "Overshoot: " + str(overshoot) + " Estimated: " + str(negOvershootEstimate)
			getNegPeak = False
			negPeak = None
			coolDataPoints.append((float(coolTime), overshoot, tempAtCoolOff, settingAtCoolOff, beerSet, float(peakTime)))
	if statePrev in coolStates and state == 0:  # move from cooling to idle
		if not coolStart:
			# error/gap in data occurred in this period, skip
			continue
		getNegPeak = True
		tempAtCoolOff = fridgeTemp
		settingAtCoolOff = fridgeSet
		negOvershootEstimate = settingAtCoolOff - tempAtCoolOff
		coolTime = date - coolStart
		if coolTime > maxCoolTimeForEstimate:
			coolTime = maxCoolTimeForEstimate
		print "Cool time: " + str(coolTime)
	if statePrev != 4 and state == 4: # start of cooling
		coolStart = date



def printTimeInfo(name, time):
	return name.ljust(30) + str(time).rjust(12) + str(round(time / timeTotal * 100, 1)).rjust(12) + "%"

print "State".ljust(30) + "Seconds".rjust(12) + "Percentage".rjust(13)
print "--------------------------------------------------------------"
print printTimeInfo("All states", timeTotal)
print printTimeInfo("Idle", idleTimeTotal)
print printTimeInfo("Off", offTimeTotal)
print printTimeInfo("Door open", doorOpenTimeTotal)
print printTimeInfo("Heating", heatingTimeTotal)
print printTimeInfo("Cooling", coolingTimeTotal)
print printTimeInfo("Waiting to cool", waitingToCoolTimeTotal)
print printTimeInfo("Waiting to heat", waitingToHeatTimeTotal)
print printTimeInfo("Waiting for peak detect", waitingForPeakDetectTimeTotal)
print printTimeInfo("Cooling minimum time", coolingMinTimeTimeTotal)
print printTimeInfo("Heating minimum time", heatingMinTimeTimeTotal)
print "\n"
print printTimeInfo("Total of idle/off states",   idleTimeTotal +
                                                  waitingToHeatTimeTotal +
                                                  waitingToCoolTimeTotal +
                                                  waitingForPeakDetectTimeTotal)
print printTimeInfo("Total of cool states:",      coolingTimeTotal +
                                                  coolingMinTimeTimeTotal)
print printTimeInfo("Total of heat states:",      heatingTimeTotal +
                                                  heatingMinTimeTimeTotal)

def graphout(data, xlabel, ylabel):
	drawing = Drawing(800, 400)
	sp = ScatterPlot()
	# sp = GridLinePlot()
	sp.data = [data]
	sp.width = 700
	sp.height = 500
	sp.xLabel = xlabel
	sp.yLabel = ylabel
	drawing.add(sp)
	return drawing

def addGraphToPdf(pdf, data, xlabel, label):
	graph = graphout(data, xlabel, label)
	# graph.save(formats=['pdf'], outDir='.', title='test1', verbose=True, fnRoot="graph")
	renderPDF.draw(graph, pdf, 0, 0)
	pdf.showPage()

# coolDataPoints.append((coolTime, overshoot, tempAtCoolOff, settingAtCoolOff, beerSet, peakTime))
pdf = canvas.Canvas("drawing.pdf")
pdf.setPageRotation(90)


data = [(x[5], x[4]) for x in coolDataPoints]
addGraphToPdf(pdf, data, "time", "beer setting")

data = [(x[5], x[0]) for x in coolDataPoints]
addGraphToPdf(pdf, data, "time", "cooling time")

data = [(x[0], x[1]) for x in coolDataPoints]
addGraphToPdf(pdf, data, "Cooling time", "overshoot")

data = [(x[5], x[1]) for x in coolDataPoints]
addGraphToPdf(pdf, data, "time", "overshoot")


def estimateOvershoot(x):
	return x[0]*5/3600

data = [(x[5], estimateOvershoot(x)) for x in coolDataPoints]
# print data
addGraphToPdf(pdf, data, "time", "Cooling time*(20-beerSet)")

pdf.save()
exit()


data = [(x[5], x[1]/x[4]) for x in coolDataPoints]
addGraphToPdf(pdf, data, "time", "overshoot / beer setting")

data = [(x[5], x[0]*x[1]/x[4]) for x in coolDataPoints]
addGraphToPdf(pdf, data, "time", "cool time * overshoot / beer setting")

data = [(x[2], x[1]/(x[0]/(x[2]))) for x in coolDataPoints]
addGraphToPdf(pdf, data, "Fridge temperature at cool off", "overshoot/fridge temp")

data = [(x[2], x[1]) for x in coolDataPoints]
addGraphToPdf(pdf, data, "Fridge temperature at cool off", "overshoot")

data = [(x[4], x[1]) for x in coolDataPoints]
addGraphToPdf(pdf, data, "Beer setting at cool off", "overshoot")


tuple1 = tuple()
tuple2 = tuple()
for x in coolDataPoints:
	datapoint1 = (x[3], x[1])
	datapoint2 = (x[3], x[0])
	tuple1 = tuple1 + (datapoint1,)
	tuple2 = tuple2 + (datapoint2,)
print tuple1

data = tuple1 + tuple2

print data
addGraphToPdf(pdf, data, "Fridge setting at cool off", "overshoot")

