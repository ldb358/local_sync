#!/usr/bin/env python2
# TODO:
# Implement getops
# add network protocol


import hashlib
import os
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler
import time
import getopt
import sys
import network

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

def hash_string(string):
	hasher = hashlib.md5()
	hasher.update(string)
	return hasher.hexdigest()



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

	def add(self, path):
		if os.path.join('.', '.') in path:
			return
		file_hash = hash_file(path)
		path_hash = path.replace(os.sep, "%sep%")
		with open(os.path.join(".sync", path_hash), "w+b") as f:
			f.write(file_hash)
		self.cache.push(path_hash, file_hash)
		return file_hash


class FileChangeHandler(PatternMatchingEventHandler):
	def __init__(self, fm, store):
		super(FileChangeHandler, self).__init__()
		self.store = store
		self.ignore = [os.path.join('.', 'sync.py'),
						os.path.join('.', 'network.py')]

	def process(self, event):
		if os.path.join(".", ".") in event.src_path:
			return
		store = self.store.get(event.src_path)
		print event.src_path
		if store and not event.src_path in self.ignore:
			print hash_file(event.src_path)

	def on_modified(self, event):
		self.process(event)

	def on_created(self, event):
		self.process(event)


class FileOps(object):
	Observer = None
	def watch(self, path):
		self.store = HashStore()
		self.observer = Observer()
		self.observer.schedule(FileChangeHandler(self, self.store),
													path, recursive=True)
		self.observer.start()

	def stop_watch(self):
		self.observer.stop()

	def get_files(self):
		return self.store.get_all_hashes()

	def set_net_callback(self, callback):
		self.net = callback

	def file_current(self, filename, filehash):
		filename = filename.replace("%sep%", os.sep)
		if(os.path.isfile(filename)):
			return self.store.get(filename) == filehash
		return False

	def open_file(self, filename, mode):
		head,tail = os.path.split(filename)
		if not os.path.isfile(filename):
			os.mkdirs(head)
		f = open(filename, mode)
		return f



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
