import sys
import urllib
import argparse
import time
import xml.etree.ElementTree as ET
import logging
import clocks

logging.basicConfig()
logger = logging.getLogger(__name__)

DEBUG=True

class NameSpace:
    def __init__(self, namespace, url):
        self.namespace = namespace
        self.url = url
        
    def ns(self):
        return { self.namespace : self.url }
        
    def __call__(self, str):
        return "{%s}%s" % (self.url, str)
        
    def __contains__(self, str):
        return str.startswith('{'+self.url+'}')
        
    def localTag(self, str):
        if str in self:
            return str[len(self.url)+2:]
        return str

NS_TIMELINE = NameSpace("tl", "http://jackjansen.nl/timelines")
NS_TIMELINE_INTERNAL = NameSpace("tls", "http://jackjansen.nl/timelines/internal")
NS_2IMMERSE = NameSpace("tim", "http://jackjansen.nl/2immerse")
NAMESPACES = {}
NAMESPACES.update(NS_TIMELINE.ns())
NAMESPACES.update(NS_2IMMERSE.ns())
NAMESPACES.update(NS_TIMELINE_INTERNAL.ns())
for k, v in NAMESPACES.items():
    ET.register_namespace(k, v)

PRIO_TO_INT = dict(low=0, normal=50, high=100)

class State:
    idle = "idle"
    initing = "initing"
    inited = "inited"
    starting = "starting"
    started = "started"
    finished = "finished"
    stopping = "stopping"
#    stopped = "stopped"
#    terminating = "terminating"
    
    NOT_DONE = {initing, inited, starting, started}
    STOP_NEEDED = {initing, inited, starting, started, finished}
    
class DummyDelegate:
    def __init__(self, elt, document, clock):
        self.elt = elt
        self.document = document
        self.state = State.idle
        self.clock = clock
        
    def __repr__(self):
        return 'Delegate(%s)' % self.document.getXPath(self.elt)
        
    def checkAttributes(self):
        pass
        
    def checkChildren(self):
        pass
        
    def storeStateForSave(self):
        if self.state != State.idle:
            self.elt.set(NS_TIMELINE_INTERNAL("state"), self.state)
            
    def setState(self, state):
        self.document.report(logging.DEBUG, 'STATE', state, self.document.getXPath(self.elt))
        if self.state == state:
            logger.warn('superfluous state change: %-8s %-8s %s' % ('STATE', state, self.document.getXPath(self.elt)))
#             if DEBUG:
#                 import pdb
#                 pdb.set_trace()
            return
        self.state = state
        parentElement = self.document.getParent(self.elt)
        if parentElement is not None:
            parentElement.delegate.reportChildState(self.elt, self.state)
           
    def assertState(self, action, *allowedStates):
        assert self.state in set(allowedStates), "%s: %s: state==%s, expected %s" % (self, action, self.state, set(allowedStates))
        
    def assertDescendentState(self, action, *allowedStates):
        for desc in self.elt.iter():
            assert desc.delegate.state in set(allowedStates), "%s: %s: descendent %s: state==%s, expected %s" % (self, action, desc.delegate, desc.delegate.state, set(allowedStates))
         
    def reportChildState(self, child, childState):
        pass
        
    def initTimelineElement(self):
        self.assertState('initTimelineElement()', State.idle)
        self.assertDescendentState('initTimelineElement()', State.idle)
        #self.setState(State.initing)
        self.setState(State.inited)
        
    def startTimelineElement(self):
        self.assertState('startTimelineElement()', State.inited)
        self.assertDescendentState('startTimelineElement()', State.idle, State.inited)
        #self.setState(State.starting)
        #self.setState(State.started)
        #self.setState(State.stopping)
        self.setState(State.finished)
        
    def stopTimelineElement(self):
        if self.state == State.idle:
            return
        self.setState(State.idle)
        
    def getCurrentPriority(self):
        return PRIO_TO_INT["low"]
        
class ErrorDelegate(DummyDelegate):
    def __init__(self, elt, document, clock):
        DummyDelegate.__init__(self, elt, document, clock)
        print >>sys.stderr, "* Error: unknown tag", elt.tag

class TimelineDelegate(DummyDelegate):
    ALLOWED_ATTRIBUTES = set()
    ALLOWED_CHILDREN = None
    EXACT_CHILD_COUNT = None
    
    def checkAttributes(self):
        for attrName in self.elt.keys():
            if attrName in NS_TIMELINE:
                if not attrName in self.ALLOWED_ATTRIBUTES:
                    print >>sys.stderr, "* Error: element", self.elt.tag, "has unknown attribute", attrName
            # Remove state attributes
            if attrName in NS_TIMELINE_INTERNAL:
                del self.elt.attrs[attrName]
                    
    def checkChildren(self):
        if not self.EXACT_CHILD_COUNT is None and len(self.elt) != self.EXACT_CHILD_COUNT:
            print >>sys.stderr, "* Error: element", self.elt.tag, "expects", self.EXACT_CHILD_COUNT, "children but has", len(self.elt)
        if not self.ALLOWED_CHILDREN is None:
            for child in self.elt:
                if child.tag in NS_2IMMERSE and not child.tag in self.ALLOWED_CHILDREN:
                    print >>sys.stderr, "* Error: element", self.elt.tag, "cannot have child of type", child.tag
         
class SingleChildDelegate(TimelineDelegate):
    EXACT_CHILD_COUNT=1

    def reportChildState(self, child, childState):
        assert child == self.elt[0]
        if self.state == State.idle:
            return
        if self.state == State.initing:
            if childState == State.inited:
                self.setState(State.inited)
                return
            assert childState == State.initing
            return
        if self.state == State.starting:
            if childState == State.started:
                self.setState(State.started)
                return
            elif childState == State.finished:
                self.setState(State.finished)
                return
            else:
                assert childState == State.starting
                return
        if self.state == State.started:
            if child.delegate.state in State.NOT_DONE:
                return
            self.setState(State.finished)
            return
        if self.state == State.stopping:
            if childState == State.idle:
                self.setState(State.idle)
                return
            assert childState == State.stopping
            return
        #import pdb ; pdb.set_trace()
        #self.assertState('reportChildState()', 'no-state-would-be-correct')

    def initTimelineElement(self):
        self.assertState('initTimelineElement()', State.idle)
        self.assertDescendentState('initTimelineElement()', State.idle)
        self.setState(State.initing)
        self.document.schedule(self.elt[0].delegate.initTimelineElement)
        
    def startTimelineElement(self):
        self.assertState('startTimelineElement()', State.inited)
        self.assertDescendentState('startTimelineElement()', State.inited, State.idle)
        self.setState(State.starting)
        self.document.schedule(self.elt[0].delegate.startTimelineElement)
        
    def stopTimelineElement(self):
        if self.state == State.idle:
            return
        self.setState(State.stopping)
        waitNeeded = False
        if self.elt[0].delegate.state in State.STOP_NEEDED:
            self.document.schedule(self.elt[0].delegate.stopTimelineElement)
            waitNeeded = True
        if not waitNeeded:
            self.setState(State.idle)

class DocumentDelegate(SingleChildDelegate):
    ALLOWED_CHILDREN={
        NS_TIMELINE("par"),
        NS_TIMELINE("seq"),
        }

class TimeElementDelegate(TimelineDelegate):
    ALLOWED_ATTRIBUTES = {
        NS_TIMELINE("prio")
        }
        
    def getCurrentPriority(self):
        val = self.elt.get(NS_TIMELINE("prio"), "normal")
#         if self.state == State.started:
#             val = self.elt.get(NS_TIMELINE("prio"), "normal")
#         else:
#             val = "low"
        val = PRIO_TO_INT.get(val, val)
        val = int(val)
        return val
        
class ParDelegate(TimeElementDelegate):
    ALLOWED_ATTRIBUTES = TimeElementDelegate.ALLOWED_ATTRIBUTES | {
        NS_TIMELINE("end"),
        NS_TIMELINE("sync"),
        }
        
    def reportChildState(self, child, childState):
        if self.state == State.idle:
            # If the <par> is idle we do not care about children changing state.
            return
        if self.state == State.initing:
            # We're initializing. Go to initialized once all our children have.
            for ch in self.elt:
                if ch.delegate.state != State.inited:
                    return
            self.setState(State.inited)
            return
        if self.state == State.starting:
            # We're starting. Wait for all our children to have started (or started-and-finished).
            for ch in self.elt:
                if ch.delegate.state not in {State.started, State.finished}:
                    return
            self.setState(State.started)
            # Note that we fall through into the next if straight away
        if self.state == State.started:
            #
            # First check whether any of the children that are relevant to our lifetime are still not finished.
            # 
            relevantChildren = self._getRelevantChildren()
#             print 'xxxjack par relevant children', relevantChildren
            for ch in relevantChildren:
                if ch.delegate.state in State.NOT_DONE:
                    return
            #
            # All timing-relevant children are done, we should terminate.
            # Terminate all our children.
            #
            # NOTE: there are some semantic issues with this. It means that
            # the children of this <par> will disappear instantly. It may be nicer to
            # have them linger on until this <par> gets a stopTimelineElement.
            # But that would mean that this <par> has no timeline anymore but
            # some of its children may still have one.
            #
            # The ultimate answer may be to add a freezeTimelineElement call
            # so we can get SMIL-like semantics.
            #
            self.setState(State.finished)
            for ch in self.elt:
                if not ch in relevantChildren:
                    if ch.delegate.state in State.STOP_NEEDED:
                        self.document.schedule(ch.delegate.stopTimelineElement)
            return
#            self.setState(State.stopping)
#             needToWait = False
#             for ch in self.elt:
#                 if ch.delegate.state == State.stopping:
# #                    print 'xxxjack par stopping, need to wait for', ch.delegate
#                     needToWait = True
#                 elif ch.delegate.state != State.stopped:
# #                    print 'xxxjack par stopping, need to stop', ch.delegate
#                     self.document.schedule(ch.delegate.stopTimelineElement)
#                     needToWait = True
#                 else:
# #                    print 'xxxjack par stopping, already stopped', ch.delegate
#                     pass
#             if not needToWait:
#                 self.setState(State.stopped)
#         elif self.state == State.stopping:
#             for ch in self.elt:
#                 if ch.delegate.state != State.stopped:
#                     return
#             self.setState(State.stopped)
#             self.assertDescendentState('reportChildState[self.state==stopped]', State.stopped, State.idle)
        if self.state == State.stopping:
            # We're stopping. When all our chadren have stopped so have we.
            for ch in self.elt:
                if ch.delegate.state != State.idle:
                    return
            self.setState(State.idle)
            return
        if self.state == State.finished:
            # We're fine with finished reports from children
            if not childState in State.NOT_DONE:
                return
        # If we get here we got an unexpected state change from a child. Report.
        logger.warn('par[%s].reportChildState(%s,%s) but self is %s' % (self.document.getXPath(self.elt), self.document.getXPath(child), childState, self.state))
    
    def _getRelevantChildren(self):
        if len(self.elt) == 0: return []
        childSelector = self.elt.get(NS_TIMELINE("end"), "all")
        if childSelector == "all":
            return list(self.elt)
        elif childSelector == "master":
            child = self._getMasterChild()
            return [child]
        assert 0, "Only all and master are implemented"
        return [self.elt[0]]
        
    def _getMasterChild(self):
        prioritiesAndChildren = []
        for ch in self.elt:
            prio = ch.delegate.getCurrentPriority()
            prioritiesAndChildren.append((prio, ch))
        prioritiesAndChildren.sort()
        return prioritiesAndChildren[-1][1]
        
        
    def initTimelineElement(self):
        self.assertState('initTimelineElement()', State.idle)
        self.assertDescendentState('initTimelineElement()', State.idle)
        self.setState(State.initing)
        for child in self.elt: 
            self.document.schedule(child.delegate.initTimelineElement)
        
    def startTimelineElement(self):
        self.assertState('startTimelineElement()', State.inited)
        self.assertDescendentState('startTimelineElement()', State.idle, State.inited)
        self.setState(State.starting)
        for child in self.elt: 
            self.document.schedule(child.delegate.startTimelineElement)
        
    def stopTimelineElement(self):
        self.setState(State.stopping)
        waitNeeded = False
        for child in self.elt:
            if child.delegate.state in State.STOP_NEEDED:
                self.document.schedule(child.delegate.stopTimelineElement)
                waitNeeded = True
        if not waitNeeded:
            self.setState(State.idle)

class SeqDelegate(TimeElementDelegate):

    def reportChildState(self, child, childState):
        assert len(self.elt)
        if self.state == State.idle:
            # We're idle. We don't care about children state changes.
            return
        if self.state == State.initing:
            # Initializing. We're initialized when our first child is.
            if self.elt[0].delegate.state != State.inited:
                return
            self.setState(State.inited)
            return
        if self.state == State.starting:
            # We're starting. Once our first child has started (or started and stopped) so have we.
            if self.elt[0].delegate.state not in {State.started, State.finished}:
                return
            self.setState(State.started)
            # Note that we fall through into the next "if" straight away.
        if self.state == State.started:
            # Started. Check whether our current child is still active.
            if self._currentChild.delegate.state in State.NOT_DONE:
                return
            # Our current child is no longer active, advance to the next (if any)
            prevChild = self._currentChild            
            nextChild = self._nextChild()
            if nextChild is None:
                 #That was the last child. We are done.
                self.setState(State.finished)
                self.assertDescendentState('reportChildState[self.state==finished]', State.finished, State.stopping, State.idle)
            elif nextChild.delegate.state == State.inited:
                # Next child is ready to run. Start it, and initialize the one after that, then stop old one.
                self._currentChild = nextChild
                self.document.schedule(self._currentChild.delegate.startTimelineElement)
                nextChild = self._nextChild()
                if nextChild is not None:
                    self.document.schedule(nextChild.delegate.initTimelineElement)
            else:
                # Next child not yet ready to run.
                nextChild.delegate.assertState('seq-parent-reportChildState()', State.initing)
                pass # Wait for inited callback from nextChild
            if prevChild is not None and prevChild.delegate.state in State.STOP_NEEDED:
                self.document.schedule(prevChild.delegate.stopTimelineElement)
        if self.state == State.stopping:
            for ch in self.elt:
                if ch.delegate.state != State.idle:
                    return
            self.setState(State.idle)
            
    def initTimelineElement(self):
        self.assertState('initTimelineElement()', State.idle)
        self.assertDescendentState('initTimelineElement()', State.idle)
        self.setState(State.initing)
        if not len(self.elt):
            self.setState(State.inited)
            return
        self._currentChild = None
        self.document.schedule(self.elt[0].delegate.initTimelineElement)
        
    def startTimelineElement(self):
        self.assertState('startTimelineElement()', State.inited)
        self.assertDescendentState('startTimelineElement()', State.idle, State.inited)
        self.setState(State.starting)
        if not len(self.elt):
            self.setState(State.finished)
            return
        self._currentChild = self.elt[0]
        self.document.schedule(self._currentChild.delegate.startTimelineElement)
        nextChild = self._nextChild()
        if nextChild is not None:
            self.document.schedule(nextChild.delegate.initTimelineElement)
                    
    def stopTimelineElement(self):
        self.setState(State.stopping)
        waitNeeded = False
        for ch in self.elt:
            if ch.delegate.state in State.STOP_NEEDED:
                self.document.schedule(ch.delegate.stopTimelineElement)
                waitNeeded = True
        if not waitNeeded:
            self.setState(State.idle)

    def _nextChild(self):
        foundCurrent = False
        for ch in self.elt:
            if foundCurrent: return ch
            foundCurrent = (ch == self._currentChild)
        return None
    
class RefDelegate(TimeElementDelegate):
    EXACT_CHILD_COUNT=0

    def startTimelineElement(self):
        self.assertState('startTimelineElement()', State.inited)
        self.assertDescendentState('startTimelineElement()', State.idle, State.inited)
        self.setState(State.starting)
        self.setState(State.started)
        self.document.report(logging.INFO, '>', 'START', self.document.getXPath(self.elt), self._getParameters())
        # XXXJACK test code. Assume text/image nodes finish straight away, masterVideo takes forever and others take 42 seconds
        cl = self.elt.get(NS_2IMMERSE("class"), "unknown")
        if cl == "mastervideo":
            return
        dur = 42
        if cl == "text" or cl == "image": 
            dur = 0
        self.clock.schedule(dur, self._done)
               
    def _done(self):
        self.document.report(logging.INFO, '<', 'finished', self.document.getXPath(self.elt))
        self.setState(State.finished)

    def stopTimelineElement(self):
        self.document.report(logging.INFO, '>', 'STOP', self.document.getXPath(self.elt))
        TimeElementDelegate.stopTimelineElement(self)
        
    def _getParameters(self):
        rv = {}
        for k in self.elt.attrib:
            if k in NS_2IMMERSE:
                rv[NS_2IMMERSE.localTag(k)] = self.elt.attrib[k]
        return rv
        
class ConditionalDelegate(SingleChildDelegate):
    ALLOWED_ATTRIBUTES = {
        NS_TIMELINE("expr")
        }

    def startTimelineElement(self):
        self.assertState('startTimelineElement()', State.inited)
        self.assertDescendentState('startTimelineElement()', State.idle, State.inited)
        self.setState(State.starting)
        self.document.report(logging.DEBUG, 'COND', True, self.document.getXPath(self.elt))
        self.document.schedule(self.elt[0].delegate.startTimelineElement)
        
class SleepDelegate(TimeElementDelegate):
    ALLOWED_ATTRIBUTES = TimeElementDelegate.ALLOWED_ATTRIBUTES | {
        NS_TIMELINE("dur")
        }

    def startTimelineElement(self):
        self.assertState('startTimelineElement()', State.inited)
        self.assertDescendentState('startTimelineElement()', State.idle, State.inited)
        self.setState(State.starting)
        self.setState(State.started)
        self.document.report(logging.DEBUG, 'SLEEP0', self.elt.get(NS_TIMELINE("dur")), self.document.getXPath(self.elt))
        dur = self.parseDuration(self.elt.get(NS_TIMELINE("dur")))
        self.clock.schedule(dur, self._done)
        
    def _done(self):
        if self.state != State.started:
            return
        self.document.report(logging.DEBUG, 'SLEEP1', self.elt.get(NS_TIMELINE("dur")), self.document.getXPath(self.elt))
        self.setState(State.finished)
    
    def parseDuration(self, dur):
        try:
            return float(dur)
        except ValueError:
            pass
        tval = time.strptime(dur, "%H:%M:%S")
        return tval.tm_sec + 60*(tval.tm_min+60*tval.tm_hour)
        
class WaitDelegate(TimelineDelegate):
    ALLOWED_ATTRIBUTES = {
        NS_TIMELINE("event")
        }
        
    def startTimelineElement(self):
        self.assertState('startTimelineElement()', State.inited)
        self.assertDescendentState('startTimelineElement()', State.idle, State.inited)
        self.setState(State.starting)
        self.document.report(logging.DEBUG, 'WAIT0', self.elt.get(NS_TIMELINE("event")), self.document.getXPath(self.elt))
        self.setState(State.started)
        self.clock.schedule(0, self._done)
        
    def _done(self):
        if self.state != State.started:
            return
        self.document.report(logging.DEBUG, 'WAIT1', self.elt.get(NS_TIMELINE("event")), self.document.getXPath(self.elt))
        self.setState(State.finished)
    
    
DELEGATE_CLASSES = {
    NS_TIMELINE("document") : DocumentDelegate,
    NS_TIMELINE("par") : ParDelegate,
    NS_TIMELINE("seq") : SeqDelegate,
    NS_TIMELINE("ref") : RefDelegate,
    NS_TIMELINE("conditional") : ConditionalDelegate,
    NS_TIMELINE("sleep") : SleepDelegate,
    NS_TIMELINE("wait") : WaitDelegate,
    }
    
class Document:
    RECURSIVE = False
        
    def __init__(self, clock):
        self.tree = None
        self.root = None
        self.clock = clock
        self.parentMap = {}
        self.toDo = []
        self.delegateClasses = {}
        self.delegateClasses.update(DELEGATE_CLASSES)
        self.terminating = False
        
    def setDelegateFactory(self, klass, tag=NS_TIMELINE("ref")):
        assert not self.root
        self.delegateClasses[tag] = klass
        
    def load(self, url):
        assert not self.root
        fp = urllib.urlopen(url)
        self.tree = ET.parse(fp)
        self.root = self.tree.getroot()
        self.parentMap = {c:p for p in self.tree.iter() for c in p}        
        
    def getParent(self, elt):
        return self.parentMap.get(elt)
        
    def getXPath(self, elt):
        assert self.root is not None
        parent = self.getParent(elt)
        if parent is None:
            return '/'
        index = 0
        for ch in parent:
            if ch is elt:
                break
            if ch.tag == elt.tag:
                index += 1
        rv = self.getXPath(parent)
        if rv != '/':
            rv += '/'
        tagname = NS_TIMELINE.localTag(elt.tag)
        rv += tagname
        if index:
            rv = rv + '[%d]' % (index+1)
        return rv
        
    def dump(self, fp):
        if self.root is None:
            return
        for elt in self.tree.iter():
            elt.delegate.storeStateForSave()
        self.tree.write(fp)
        fp.write('\n')
        
    def dumps(self):
        if self.root is None:
            return ''
        for elt in self.tree.iter():
            elt.delegate.storeStateForSave()
        xmlstr = ET.tostring(self.root, encoding='utf8', method='xml')
        return xmlstr
    
    def addDelegates(self):
        assert self.root is not None
        for elt in self.tree.iter():
            if not hasattr(elt, 'delegate'):
                klass = self._getDelegate(elt.tag)
                elt.delegate = klass(elt, self, self.clock)
                elt.delegate.checkAttributes()
                elt.delegate.checkChildren()
                
    def _getDelegate(self, tag):
        if not tag in NS_TIMELINE:
                return DummyDelegate
        return self.delegateClasses.get(tag, ErrorDelegate)
            
    def runDocument(self):
        self.runDocumentInit()
        if not self.RECURSIVE:
            self.runloop(State.inited)
        self.clock.start()
        self.runDocumentStart()
        self.runloop(State.finished)
        self.report(logging.DEBUG, 'RUN', 'stop')
        self.root.delegate.assertDescendentState("run()", State.finished, State.stopping, State.idle)
#        self.terminating = True
        self.root.delegate.stopTimelineElement()
        self.runloop(State.idle)
        self.root.delegate.assertDescendentState("run()", State.idle)
        self.report(logging.DEBUG, 'RUN', 'done')
            
    def runDocumentInit(self):
        self.report(logging.DEBUG, 'RUN', 'init')
        self.schedule(self.root.delegate.initTimelineElement)
    
    def runDocumentStart(self):
        assert self.root is not None
        self.report(logging.DEBUG, 'RUN', 'start')
        self.schedule(self.root.delegate.startTimelineElement)

    def getDocumentState(self):
        if self.root is None:
            return None
        return self.root.delegate.state
            
    def schedule(self, callback, *args, **kwargs):
        assert self.root is not None
        self.report(logging.DEBUG, 'EMIT', callback.__name__, self.getXPath(callback.im_self.elt))
        if self.RECURSIVE or self.terminating:
            callback(*args, **kwargs)
        else:
            self.toDo.append((callback, args, kwargs))
            
    def runloop(self, stopstate):
        assert self.root is not None
        while self.root.delegate.state != stopstate or len(self.toDo):
            if len(self.toDo):
                callback, args, kwargs = self.toDo.pop(0)
                callback(*args, **kwargs)
            else:
                self.sleepUntilNextEvent()
                self.clock.handleEvents(self)
        assert len(self.toDo) == 0, 'events not handled: %s' % repr(self.toDo)
        assert self.root.delegate.state == stopstate, 'Document root did not reach state %s' % stopstate
        
    def sleepUntilNextEvent(self):
        self.clock.sleepUntilNextEvent()
        
    def runAvailable(self):
        assert self.root is not None
        self.clock.handleEvents(self)
        while len(self.toDo):
            callback, args, kwargs = self.toDo.pop(0)
            callback(*args, **kwargs)
            if len(self.toDo) == 0:
                self.clock.handleEvents(self)

    def report(self, level, event, verb, *args):
        if args:
            args = reduce((lambda h, t: str(h) + ' ' + str(t)), args)
        else:
            args = ''
        logger.log(level, '%8.3f %-8s %-22s %s', self.clock.now(), event, verb, args)
             
def main():
    global DEBUG
    parser = argparse.ArgumentParser(description="Test runner for timeline documents")
    parser.add_argument("document", help="The XML timeline document to parse and run")
    parser.add_argument("--debug", action="store_true", help="Print detailed state machine progression output")
    parser.add_argument("--trace", action="store_true", help="Print less detailed externally visible progression output")
    parser.add_argument("--dump", action="store_true", help="Dump document to stdout on exceptions and succesful termination")
    parser.add_argument("--fast", action="store_true", help="Use fast-forward clock in stead of realtime clock")
    parser.add_argument("--recursive", action="store_true", help="Debugging: use recursion for callbacks, not queueing")
    args = parser.parse_args()
    DEBUG = args.debug
    if DEBUG:
        logger.setLevel(logging.DEBUG)
    elif args.trace:
        logger.setLevel(logging.INFO)
    if args.recursive: Document.RECURSIVE=True
    
    if args.fast:
        clock = clocks.CallbackPausableClock(clocks.FastClock())
    else:
        clock = clocks.CallbackPausableClock(clocks.SystemClock())
    
    d = Document(clock)
    try:
        d.load(args.document)
        d.addDelegates()
#         if args.dump:
#             d.dump(sys.stdout)
#             print '--------------------'
        d.runDocument()
    finally:
        if args.dump:
            print '--------------------'
            #d.dump(sys.stdout)
            print d.dumps()
    
if __name__ == '__main__':
    main()