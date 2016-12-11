#!/usr/bin/python
import sys
import json

def genScrollText(fileName, firstTime, lastTime, interval):
    fp = open(fileName, "w")
    fp.write("[\n")
    curTime = firstTime
    count = 0
    while curTime < lastTime:
        if count > 0:
            fp.write(',\n')
        ct = int(curTime)
        h = int(ct / 3600)
        m = int((ct / 60) % 60)
        s = int(ct % 60)
        item = dict(
            category="dialogue",
            who="timecode",
            text="%02.2d:%02.2d:%02.2d" % (h, m, s),
            time=dict(h=h, m=m, s=s)
            )
        data = json.dumps(item)
        fp.write(data)
        curTime += interval
        count += 1
    fp.write("\n]\n")
    return count
    
def main():
    if len(sys.argv) != 5:
        print "Usage: %s outputfile starttime endtime interval" % sys.argv[0]
        print "Times are all in seconds. Generates scrolltext document with timecodes."
        sys.exit(1)
    count = genScrollText(sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]))
    print 'Created %d lines' % count
    
if __name__ == '__main__':
    main()
    
        
