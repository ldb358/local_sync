#!/usr/bin/env python2
#
# Uses libraries: watchdog
#


import hashlib
import os
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler
import time
import getopt
import sys
import network
import threading


#
# Creates an md5 hash based on the file
#
def hash_file(filename, block_size=4048):
	hasher = hashlib.sha256()
	while not os.path.exists(filename):
		pass
	with open(str(filename), 'rb') as f:
		buf = f.read(block_size)
		while len(buf) > 0:
			hasher.update(buf)
			if len(buf) == block_size:
				buf = f.read(block_size)
			else:
				break
	return hasher.hexdigest()

#
# Hashs a normal string
#
def hash_string(string):
	hasher = hashlib.md5()
	hasher.update(string)
	return hasher.hexdigest()

#
# A timer that runs in a seperate thread and can be reset
#
class ResetTimer(object):
	def __init__(self,dur, f, args):
		self.f = f
		self.args = args
		self.timer = None
		self.duration = dur

	def reset(self):
		self.timer.cancel()
		self.timer = threading.Timer(self.duration, self.f, self.args)
		self.timer.start()

	def cancel(self):
		self.timer.cancel()

	def start(self):
		self.timer = threading.Timer(self.duration, self.f, self.args)
		self.timer.start()


#
# Data structure for maintaining the cache that contains a disctionary for the
# entries and a queue to keep track of what items to remove
#
class DictQueue(object):
	max_s = 0
	queue = None
	table = None
	def __init__(self, max_s=10):
		self.max_s = max_s
		self.table = {}
		self.queue = []

	def push(self, key, val):
		self.table[key] = val
		try:
			#if the key is in the queue move it to the end
			self.queue.remove(key)
			self.queue.append(key)
		except ValueError:
			#if its not in the queue, is the queue full?
			if len(self.table) < self.max_s:
				#no. just add the value
				self.queue.append(key)
			else:
				#pop the top value from the queue and append the new key
				old = self.queue.pop()
				self.queue.append(key)
				#remove the old value
				del self.table[old]

	def get(self, key):
		return self.table.get(key, False)

# Create the hash storage mechnism(HashStore)
# 	all file hashes should be in the .sync folder and be one hash per file
#	the name of the file should be the hash of the filename
#	the cache should store the hashs for the last 10 accessed files
# 	they should be stored with a queue and dirctionary where the queue keeps track of the
# 	least recently changed
class HashStore(object):
	def __init__(self):
		self.cache = DictQueue()
		if not os.path.exists(os.path.join(".", ".sync")):
			os.mkdir(".sync")
		for root, dirs, files in os.walk('.sync'):
			for name in files:
				path = os.path.join(root, name)
				os.unlink(path)
		for root, dirs, files in os.walk('.'):
			for name in files:
				path = os.path.join(root, name)
				self.add(path)

	#get the current hash for all files
	def get_all_hashes(self):
		hashes = {}
		for root, dirs, files in os.walk(os.path.join(".", ".sync")):
			for name in files:
				path = os.path.join(root, name)
				with open(path, "r") as f:
					file_hash = f.read()
				name = os.path.basename(path)
				hashes[name] = file_hash
		return hashes

	#gets the hash for a file
	def get(self, path):
		file_hash = hash_file(path)
		path_hash = path.replace(os.sep, "%sep%")
		cached = self.cache.get(file_hash)
		#any value is okay expect expliclity False
		if not cached == False:
			return cached
		try:
			with open(os.path.join(".sync", path_hash), "r") as f:
				file_hash = f.read()
			self.cache.push(path_hash, file_hash)
			return file_hash
		except IOError:
			with open(os.path.join(".sync", path_hash), "w+b") as f:
				f.write(file_hash)
			self.cache.push(path_hash, file_hash)
			return file_hash

	#adds a file to the hased directory
	def add(self, path):
		if os.path.join('.', '.') in path:
			return
		file_hash = hash_file(path)
		path_hash = path.replace(os.sep, "%sep%")
		with open(os.path.join(".sync", path_hash), "w+b") as f:
			f.write(file_hash)
		self.cache.push(path_hash, file_hash)
		return file_hash

#
# Uses the watch dog library to wait for file changes
#
class FileChangeHandler(PatternMatchingEventHandler):
	#set up our hash store and ignore our source files
	def __init__(self, fm, store):
		super(FileChangeHandler, self).__init__()
		self.store = store
		self.ignore = [os.path.join('.', 'sync.py'),
						os.path.join('.', 'network.py')]
		self.delays = {}

	# Procceses a file change by hashing it and making a callback to the
	# networking thread so we have transmit the file if needed
	def process(self, event, nw=False):
		if os.path.join(".", ".") in event.src_path or "TerraCopy" in event.src_path:
			return
		#get the stored version of the hash
		store = self.store.get(event.src_path)
		#if the file is not ignored(which happens when we are editing it)
		if (not event.src_path in self.ignore):
			#print a message
			print "File Changed",event.src_path, "With Hash", hash_file(event.src_path)
			#hash the file and get a operating system independent filename
			fn = event.src_path.replace(os.sep, "%sep%")
			hs = hash_file(event.src_path)
			if nw:
				#its a new file
				self.file_updated(event.src_path, '', hs)
			else:
				#its an old file
				self.file_updated(event.src_path, store, hs)

	def on_modified(self, event):
		self.file_ready(event, nw=False)

	def on_created(self, event):
		self.file_ready(event, nw=True)

	# this is called when a change is made. A timer is then set and whenever a
	# a change is made to the file the timer is reset
	def file_ready(self, event, nw):
		if not self.delays.get(event.src_path, False):
			self.delays[event.src_path] = ResetTimer(1, self.process, args=(event, nw))
			self.delays[event.src_path].start()
		else:
			self.delays[event.src_path].reset()

	# add a file to the ignore list
	def add_ignore(self, fn):
		self.ignore.append(fn)

	# remove a file from the ignore list
	def remove_ingore(self, fn):
		timer =threading.Timer(2, self.ignore.remove, (fn,))
		timer.start()

	# sets a callback
	def set_file_update_callback(self, callback):
		self.file_updated = callback

# acts as a moderator between the network class and the filewatcher class
class FileOps(object):
	Observer = None
	#starts the watcher up
	def watch(self, path):
		self.store = HashStore()
		self.observer = Observer()
		self.file_change = FileChangeHandler(self, self.store)
		self.observer.schedule(self.file_change, path, recursive=True)
		self.observer.start()

	#stop the watcher
	def stop_watch(self):
		self.observer.stop()

	# get all of the files in the directory
	def get_files(self):
		return self.store.get_all_hashes()

	#sets the network callback
	def set_net_callback(self, callback):
		self.net = callback
		self.file_change.set_file_update_callback(callback)

	#checks if the file match a hash
	def file_current(self, filename, filehash):
		filename = filename.replace("%sep%", os.sep)
		if(os.path.isfile(filename)):
			return self.store.get(filename) == filehash
		return False

	#opens a file and adds the file to the ignore list, which prevents a file
	#change from being proced while we are writing/reading from it
	def open_file(self, filename, mode):
		filename = self.net_path_to_local(filename)
		head,tail = os.path.split(filename)
		if not os.path.isfile(filename):
			if not os.path.isdir(head):
				os.makedirs(head)
		self.file_change.add_ignore(filename)
		f = open(filename, mode)
		return f

	#closes the file
	def close_file(self, filename, f):
		filename = self.net_path_to_local(filename)
		f.close()
		self.file_change.remove_ingore(filename)

	#converts our network path to a local path
	def net_path_to_local(self, filename):
		return filename.replace("%sep%", os.sep)



if __name__ == "__main__":
	fm = FileOps()
	fm.watch(".")
	# Use get opt to get all of out command line arguments
	optlist, args = getopt.getopt(sys.argv[1:], 'sc:p:g:k:')
	if(len(optlist) < 4):
		print "you must have the following arguments:"
		print "-s : launch as a server or you can have -c"
		print "-c [ip] : the ip address of the server for the client to connect to"
		print "-p [portno] : the port number to connect to or create the server on"
		print "-g [group name] : the group name to connect to"
		print "-k [passkey] : the pass key yo use for login"
		sys.exit()
	port = -1
	server = ''
	is_server = False
	group = 'default'
	passkey = 'default'
	for arg in optlist:
		if arg[0] == '-s':
			is_server = True
		elif arg[0] == '-c':
			server = arg[1]
		elif arg[0] == '-p':
			port = int(arg[1])
		elif arg[0] == '-g':
			group = arg[1]
		elif arg[0] == '-k':
			passkey = arg[1]
		else:
			print "Invalid argument:", arg
	# depending on whether we are a server or client we need a different handler
	# class
	if is_server:
		net_conn = network.ServerNetworkInterface('', port, group, passkey)
	else:
		net_conn = network.ClientNetworkInterface(server, port, group, passkey)
	#set the callbacks
	net_conn.set_file_manager(fm)
	fm.set_net_callback(net_conn.update)
	try:
		#loop while waiting for files
		while not net_conn.stop:
			time.sleep(1)
	except KeyboardInterrupt:
		fm.stop_watch()
		net_conn.stop_net()
		print "Exiting, please wait while everything is cleaned up"
