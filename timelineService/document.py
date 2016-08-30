import sys
import urllib
import xml.etree.ElementTree as ET

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

class State:
    idle = "idle"
    initing = "initing"
    inited = "inited"
    starting = "starting"
    started = "started"
    stopping = "stopping"
    stopped = "stopped"
#    terminating = "terminating"
    
#    DONE = {stopping, stopped, terminating}
    DONE = {stopping, stopped}
    READY = {inited}
    
class DummyDelegate:
    def __init__(self, elt, document):
        self.elt = elt
        self.document = document
        self.state = State.idle
        
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
        if DEBUG: print '%-8s %-8s %s' % ('STATE', state, self.document.getXPath(self.elt))
        if self.state == state:
            print 'xxxjack superfluous state change: %-8s %-8s %s' % ('STATE', state, self.document.getXPath(self.elt))
            if DEBUG:
                import pdb
                pdb.set_trace()
            return
        self.state = state
        parentElement = self.document.getParent(self.elt)
        #print 'xxxjack parent is', parentElement
        if parentElement is not None:
            parentElement.delegate.reportChildState(self.elt, self.state)
           
    def assertState(self, *allowedStates):
        assert self.state in set(allowedStates), "%s: state==%s, expected %s" % (self, self.state, set(allowedStates))
         
    def reportChildState(self, child, childState):
        pass
        
    def init(self):
        self.assertState(State.idle)
        self.setState(State.initing)
        self.setState(State.inited)
        
    def start(self):
        self.assertState(State.inited, State.stopped)
        self.setState(State.starting)
        #self.setState(State.started)
        #self.setState(State.stopping)
        self.setState(State.stopped)
        
    def stop(self):
        self.assertState(State.inited, State.started)
        self.setState(State.stopping)
        self.setState(State.stopped)
        
#     def terminate(self):
#         self.assertState(State.stopped)
#         self.setState(State.terminating)
#         self.setState(State.idle)
        
class ErrorDelegate(DummyDelegate):
    def __init__(self, elt):
        DummyDelegate.__init__(self, elt)
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
        if childState == State.inited:
            self.assertState(State.initing)
            self.setState(State.inited)
        elif childState == State.started:
            self.assertState(State.starting)
            self.setState(State.started)
        elif childState == State.stopped:
            self.assertState(State.stopping, State.started)
            self.setState(State.stopped)

    def init(self):
        self.assertState(State.idle)
        self.setState(State.initing)
        self.document.schedule(self.elt[0].delegate.init)
        
    def start(self):
        self.assertState(State.inited, State.stopped)
        self.setState(State.starting)
        self.document.schedule(self.elt[0].delegate.start)
        
    def stop(self):
        self.assertState(State.inited, State.started)
        self.setState(State.stopping)
        self.document.schedule(self.elt[0].delegate.stop)
        
#     def terminate(self):
#         self.assertState(State.stopped)
#         self.setState(State.terminating)
#         self.document.schedule(self.elt[0].delegate.terminate)
#         self.setState(State.idle)

class DocumentDelegate(SingleChildDelegate):
    ALLOWED_CHILDREN={
        NS_TIMELINE("par"),
        NS_TIMELINE("seq"),
        }

class TimeElementDelegate(TimelineDelegate):
    ALLOWED_ATTRIBUTES = {
        NS_TIMELINE("prio")
        }
        
class ParDelegate(TimeElementDelegate):
    ALLOWED_ATTRIBUTES = TimeElementDelegate.ALLOWED_ATTRIBUTES | {
        NS_TIMELINE("end"),
        NS_TIMELINE("sync"),
        }
        
    def reportChildState(self, child, childState):
        if self.state == State.initing:
            for ch in self.elt:
                if ch.delegate.state != State.inited:
                    return
            self.setState(State.inited)
        elif self.state == State.starting:
            for ch in self.elt:
                if ch.delegate.state not in {State.started, State.stopped}:
                    return
            self.setState(State.started)
        elif self.state == State.started:
            relevantChildren = self._getRelevantChildren()
            for ch in relevantChildren:
                if ch.delegate.state != State.stopped:
                    return
            self.setState(State.stopping)
            needToWait = False
            for ch in self.elt:
                if ch.delegate.state == State.stopping:
                    needToWait = True
                elif ch.delegate.state != State.stopped:
                    self.document.schedule(ch.delegate.stop)
                    needToWait = True
            if not needToWait:
                self.setState(State.stopped)
        elif self.state == State.stopping:
            for ch in self.elt:
                if ch.delegate.state != State.stopped:
                    return
            self.setState(State.stopped)
    
    def _getRelevantChildren(self):
        # Stopgap
        if len(self.elt) == 0: return []
        if self.elt.get(NS_TIMELINE("end"), "all") == "all":
            return list(self.elt)
        return self.elt[0]     
        
    def init(self):
        self.assertState(State.idle)
        self.setState(State.initing)
        for child in self.elt: 
            self.document.schedule(child.delegate.init)
        
    def start(self):
        self.assertState(State.inited, State.stopped)
        self.setState(State.starting)
        for child in self.elt: 
            self.document.schedule(child.delegate.start)
        
    def stop(self):
        self.assertState(State.inited, State.started)
        self.setState(State.stopping)
        for child in self.elt: 
            self.document.schedule(child.delegate.stop)
        
#     def terminate(self):
#         self.assertState(State.stopped)
#         self.setState(State.terminating)
#         for child in self.elt: 
#             self.document.schedule(child.delegate.terminate)
#         self.setState(State.idle)

class SeqDelegate(TimeElementDelegate):

    def reportChildState(self, child, state):
        # Ignore arguments, for now
        # xxxjack need to model after ParDelegate
        if self._currentChild is None:
            return
        if self._currentChild.delegate.state not in State.DONE:
            return
        nextChild = self._nextChild()
        if nextChild is None or nextChild.delegate.state in State.READY:
            self._startFollowingChild()
        
    def init(self):
        self.assertState(State.idle)
        self.setState(State.initing)
        self._currentChild = None
        self.document.schedule(self.elt[0].delegate.init)
        self.setState(State.inited)
        
    def start(self):
        self.assertState(State.inited, State.stopped)
        self.setState(State.starting)
        self._currentChild = self.elt[0]
        self.document.schedule(self._currentChild.delegate.start)
        self.setState(State.started)
        nextChild = self._nextChild()
        if nextChild is not None:
            self.document.schedule(nextChild.delegate.init)
            
    def _startFollowingChild(self):
        if self._currentChild is not None:
            self._currentChild.delegate.assertState(State.stopped, State.stopping)
#            self.document.schedule(self._currentChild.delegate.terminate)
        self._currentChild = self._nextChild()
        if self._currentChild is not None:
            self.document.schedule(self._currentChild.delegate.start)
            nextChild = self._nextChild()
            if nextChild is not None:
                self.document.schedule(nextChild.delegate.init)
        else:
            self.stop()
        
    def stop(self):
        self.assertState(State.inited, State.started)
        self.setState(State.stopping)
        if self._currentChild is not None:
            self.document.schedule(self._currentChild.delegate.stop)
        self.setState(State.stopped)
        
#     def terminate(self):
#         self.assertState(State.stopped)
#         self.setState(State.terminating)
#         if self._currentChild is not None:
#             self.document.schedule(self._currentChild.delegate.terminate)
#         # xxxjack: do anything about nextChild?
#         self.setState(State.idle)

    def _nextChild(self):
        foundCurrent = False
        for ch in self.elt:
            if foundCurrent: return ch
            foundCurrent = (ch == self._currentChild)
        return None
    
class RefDelegate(TimeElementDelegate):
    EXACT_CHILD_COUNT=0

    def start(self):
        self.assertState(State.inited, State.stopped)
        self.setState(State.starting)
        self.setState(State.started)
        if DEBUG: print '%-8s %-8s %s' % ('-', 'present', self.document.getXPath(self.elt))
        self.setState(State.stopped)
    
class ConditionalDelegate(SingleChildDelegate):
    ALLOWED_ATTRIBUTES = {
        NS_TIMELINE("expr")
        }

    def start(self):
        self.assertState(State.inited, State.stopped)
        self.setState(State.starting)
        if DEBUG: print '%-8s %-8s %s' % ('COND', True, self.document.getXPath(self.elt))
        self.document.schedule(self.elt[0].delegate.start)
        
class SleepDelegate(TimeElementDelegate):
    ALLOWED_ATTRIBUTES = TimeElementDelegate.ALLOWED_ATTRIBUTES | {
        NS_TIMELINE("dur")
        }

    def start(self):
        self.assertState(State.inited, State.stopped)
        self.setState(State.starting)
        self.setState(State.started)
        if DEBUG: print '%-8s %-8s %s' % ('SLEEP0', self.elt.get(NS_TIMELINE("dur")), self.document.getXPath(self.elt))
        if DEBUG: print '%-8s %-8s %s' % ('SLEEP1', self.elt.get(NS_TIMELINE("dur")), self.document.getXPath(self.elt))
        self.setState(State.stopped)
    
    
class WaitDelegate(TimelineDelegate):
    ALLOWED_ATTRIBUTES = {
        NS_TIMELINE("event")
        }
        
    def start(self):
        self.assertState(State.inited, State.stopped)
        self.setState(State.starting)
        if DEBUG: print '%-8s %-8s %s' % ('WAIT0', self.elt.get(NS_TIMELINE("event")), self.document.getXPath(self.elt))
        self.setState(State.started)
        if DEBUG: print '%-8s %-8s %s' % ('WAIT1', self.elt.get(NS_TIMELINE("event")), self.document.getXPath(self.elt))
        self.setState(State.stopped)
    
    
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
        
    def __init__(self):
        self.tree = None
        self.root = None
        self.parentMap = {}
        self.toDo = []
        
    def load(self, url):
        fp = urllib.urlopen(url)
        self.tree = ET.parse(fp)
        self.root = self.tree.getroot()
        self.parentMap = {c:p for p in self.tree.iter() for c in p}        
        
    def getParent(self, elt):
        return self.parentMap.get(elt)
        
    def getXPath(self, elt):
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
        for elt in self.tree.iter():
            elt.delegate.storeStateForSave()
        self.tree.write(fp)
        fp.write('\n')
        
    def addDelegates(self):
        for elt in self.tree.iter():
            if not hasattr(elt, 'delegate'):
                klass = self._getDelegate(elt.tag)
                elt.delegate = klass(elt, self)
                elt.delegate.checkAttributes()
                elt.delegate.checkChildren()
                
    def _getDelegate(self, tag):
        if not tag in NS_TIMELINE:
                return DummyDelegate
        return DELEGATE_CLASSES.get(tag, ErrorDelegate)
            
    def run(self):
        self.schedule(self.root.delegate.init)
        if not self.RECURSIVE:
            self.runloop(State.inited)
        self.schedule(self.root.delegate.start)
        if not self.RECURSIVE:
            self.runloop(State.stopped)
            
            
    def schedule(self, callback, *args, **kwargs):
        if DEBUG: print '%-8s %-8s %s' % ('EMIT', callback.__name__, self.getXPath(callback.im_self.elt))
        if self.RECURSIVE:
            callback(*args, **kwargs)
        else:
            self.toDo.append((callback, args, kwargs))
            
    def runloop(self, stopstate):
        assert not self.RECURSIVE
        while self.toDo:
            callback, args, kwargs = self.toDo.pop(0)
            callback(*args, **kwargs)
            if self.root.delegate.state == stopstate:
                break
        assert len(self.toDo) == 0, 'events not handled: %s' % repr(self.toDo)
        
def main():
    d = Document()
    try:
        d.load(sys.argv[1])
        d.addDelegates()
        d.dump(sys.stdout)
        print '--------------------'
        d.run()
    finally:
        print '--------------------'
        d.dump(sys.stdout)
    
if __name__ == '__main__':
    main()
