#!/usr/bin/env python2
# TODO:
# Get directory watching working
#	on init create a HashStore()
#	walk the directory and create a hash for every file in order
# 	start watching the directoy


import hashlib
import os
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler
import time

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

		for root, dirs, files in os.walk('.'):
			for name in files:
				path = os.path.join(root, name)
				self.add(path)

	def get(self, path):
		file_hash = hash_file(path)
		path_hash = hash_string(path)
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
		path_hash = hash_string(path)
		with open(os.path.join(".sync", path_hash), "w+b") as f:
			f.write(file_hash)
		self.cache.push(path_hash, file_hash)
		return file_hash


class FileChangeHandler(PatternMatchingEventHandler):
	def __init__(self, fm):
		super(FileChangeHandler, self).__init__()
		self.store = HashStore()

	def process(self, event):
		if os.path.join(".", ".") in event.src_path:
			return
		store = self.store.get(event.src_path)
		if store:
			print hash_file(event.src_path)

	def on_modified(self, event):
		self.process(event)

	def on_created(self, event):
		self.process(event)


class FileOps(object):
	Observer = None
	def watch(self, path):
		self.observer = Observer()
		self.observer.schedule(FileChangeHandler(self), path, recursive=True)
		self.observer.start()

	def stop_watch(self):
		self.observer.stop()


if __name__ == "__main__":
	fm = FileOps()
	fm.watch(".")
	try:
		while True:
			time.sleep(1)
	except KeyboardInterrupt:
		fm.stop_watch()
