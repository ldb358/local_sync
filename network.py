import threading
import socket
import select
import json
import hashlib
import time
import sys
import os

#
# 'interface'= class for all Networking interfaces(both client and server
#  decend from this)
#
class SyncNetworkInterface(object):
    def __init__(self, ip, port, group='default', pkey='default'):
        self.ip = ip
        self.port = port
        self.group = group
        self.pkey = pkey
        self.stop = False
        self.init_connection()
        self.op_queue = []

    def init_connection(self):
        raise NotImplementedError("Please Implement this method")

    def file_updated(self):
        raise NotImplementedError("Please Implement this method")

    # generates an auth token, used to verify login
    def get_auth(self):
    	hasher = hashlib.md5()
    	hasher.update(self.group+self.pkey)
    	return hasher.hexdigest()

    # this flag is used for thread sync allowing the main thread to stop the
    # the network thread
    def stop_net(self):
        self.stop = True

    #creates a json string for the standard error message
    def create_error_message(self, message):
        m = {
            "type": "error",
            "error": message
        }
        return json.dumps(m)

    #sets a file manager for the class to use
    def set_file_manager(self, fm):
        self.fm = fm

    def update(self):
        raise NotImplementedError("Please Implement this method")

class ServerNetworkInterface(SyncNetworkInterface):
    #
    # This will setup the server and spawin a thread that will do nothing but
    # wait for data and spawn new threads
    #
    def init_connection(self):
        #open an INET TCP socket
        self.serversocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        #bind the socket to any host and the given port
        self.serversocket.bind((self.ip, self.port))
        waiting = threading.Thread(target=self.wait_for_connections)
        waiting.start()

    #
    # This class will listen to the sockets and wait for any to have data to
    # read when it does it will spawn a thread to handle it
    #
    def wait_for_connections(self):
        self.serversocket.listen(5)
        #create a list that will have all of our client sockets in it
        self.current_clients = [self.serversocket]
        #keep track of the number of runnin threads we have
        self.running = 0
        while not self.stop:
            #select all sockets that have data to be read or have an error
            readable, writable, errored = select.select(self.current_clients, [], self.current_clients[1:], 1)
            #loop through all the ones with data
            for s in readable:
                if s is self.serversocket:
                    #if its our server socket it means we have a new cleint
                    conn, addr = self.serversocket.accept()
                    print 'Connected by', addr
                    self.current_clients.append(conn)
                else:
                    #otherwise is means we have data so spawn a new thread to handle it

                    #remove the client from the list while we respond to its request
                    self.current_clients.remove(s)
                    #handle the request
                    thread = threading.Thread(target=self.handle_client, args=(s,))
                    thread.start()
            for s in errored:
                self.current_clients.remove(s)
            # run any operation that need to be run from the file io thread
            # this is only run when we have no threads working so that we don't
            # interurupt any on going transactions
            while len(self.op_queue) > 0 and self.running == 0:
                item = self.op_queue.pop(0)
                self.call_update(item[0], item[1], item[2])
        self.serversocket.close()

    def handle_client(self, conn):
        #keep track of how many are running
        self.running += 1
        #read the entire message from the client
        all_data = ''
        while 1:
            data = conn.recv(1024)
            all_data += data
            if len(data) < 1024: break
        if len(all_data) == 0:
            return
        #parse the json message
        message = json.loads(all_data.strip())
        #depending on the type of message call the correct handler
        try:
            if message["type"] == "auth":
                self.auth(conn, message)
            elif message["type"] == "request":
                self.request(conn, message["name"])
            elif message["type"] == "push":
                self.push(conn, message["name"], int(message["size"]), message["hash"])
            elif message["type"] == "error":
                print message["error"]
        except KeyError:
            conn.sendall(self.create_error_message("Missing Field in Request"))
        #keep track of the the number of threads
        self.running -= 1

    #
    # Handles a push Request from the client by downloading the file from them
    #
    def push(self, conn, filename, filesize, old_hash):
        #convert the file for use with the filesystem
        fn = filename.replace("%sep%", os.sep)
        if self.fm.file_current(filename, old_hash) or (old_hash=='' and not os.path.exists(fn)):
            #let the client know to send the file
            ready = {
                "type": "send"
            }
            conn.sendall(json.dumps(ready))
            data = ''
            downloaded = 0
            #open the local file
            f = self.fm.open_file(filename, "wb")
            print "Downloading:", filename.replace("%sep%", os.sep)
            #while there is more file
            while downloaded < filesize:
                # get the next chunk
                data = conn.recv(1024)
                # keep track of how much we have
                downloaded += len(data)
                #write it to the file
                f.write(data)
                progress = int(float(downloaded)/filesize*100)
                print progress,
                sys.stdout.flush()
            print
            self.fm.close_file(filename, f)
        else:
            conn.sendall(self.create_error_message("Invalid file hash"))

        self.current_clients.append(conn)

    #validates the login of the connecting client
    def auth(self, client, message):
        if message["group"] == self.group and message["token"] == self.get_auth():
            retmsg = {
                "type": "accept",
                "files": self.fm.get_files()
            }
            #let the cleint know that we accepted them and send a current list of all files
            client.sendall(json.dumps(retmsg))
            #put the client back in the list
            self.current_clients.append(client)
        else:
            client.sendall(self.create_error_message("Invalid Authentication"))
            client.close()

    #handles a request for a file
    def request(self, client, filename):
        #convert the file for use with the filesystem
        fn = filename.replace("%sep%", os.sep)
        #if we dont have the file send an error
        if not os.path.isfile(fn):
            client.sendall(self.create_error_message("File Does Not Exist"))
            client.close()
            return
        response = {
            "type": "download",
            "size": os.path.getsize(fn),
            "name": filename
        }
        #send them the info for the file
        client.sendall(json.dumps(response))
        #wait for a ready message from the client
        ready = client.recv(1)
        if ready == "r":
            #upload the file to the client
            f = self.fm.open_file(filename, "rb")
            while 1:
                data = f.read(1024)
                if not data: break
                client.sendall(data)
            self.fm.close_file(filename, f)
        #add the client back to the list
        self.current_clients.append(client)

    def update(self, filename, oldhash, filehash):
        for i in self.op_queue:
            if i[0] == filename:
                self.op_queue.remove(i)
        self.op_queue.append([filename, oldhash, filehash])

    def call_update(self, filename, oldhash, filehash):
        packet = {
            "type": "update",
            "name": filename,
            "old": oldhash,
            "new": filehash
        }
        print "Change to", filename
        strpacket = json.dumps(packet)
        try:
            readable, writable, errored = select.select([], self.current_clients[1:], [], 1)
            for conn in writable:
                conn.sendall(strpacket)
        except:
            pass

class ClientNetworkInterface(SyncNetworkInterface):
    def init_connection(self):
        self.client_s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.client_s.connect((self.ip, self.port))
        #the first message we have to send is an auth message
        message = {
            "type": "auth",
            "group": self.group,
            "token": self.get_auth()
        }
        self.client_s.sendall(json.dumps(message))
        listen = threading.Thread(target=self.handle_response, args=(self.client_s,))
        listen.start()

    # seperate thread that loops until stop=True and reads data from the socket
    # when avalable
    def handle_response(self, conn):
        while not self.stop:
            readable, writable, errored = select.select([conn], [], [], 1)
            for s in readable:
                all_data = ''
                while not self.stop:
                    data = s.recv(1024)
                    all_data += data
                    if len(data) < 1024: break
                if len(all_data) == 0:
                    time.sleep(.1)
                    continue
                message = json.loads(all_data)
                if message["type"] == "accept":
                    self.setup_files(conn, message["files"])
                elif message["type"] == "update":
                    self.update_file(message["name"], message["new"])
                elif message["type"] == "error":
                    print "Error:", message["error"]
                    #stop this thread
                    self.stop_net()
                    #stop the file watching thread
                    self.fm.stop_watch()
                else:
                    print message
            while len(self.op_queue) > 0:
                item = self.op_queue.pop(0)
                self.call_update(item[0], item[1], item[2])

        conn.close()
    #
    # loops through each file that the server has and makes sure that our
    # version is up to date, if its not we download it
    #
    def setup_files(self, conn, files):
        #
        # for every file we need to see if we have a version that matches the
        # server if not we need to downloaded it
        #
        for key in files:
            #check if out version is current
            if(not self.fm.file_current(key, files[key])):
                self.get_file(key)

    #
    # handles an update type request by seeing if our file matchs the new file
    # if not it downloads it
    #
    def update_file(self, filename, new_hash):
        if(not self.fm.file_current(filename, new_hash)):
            self.get_file(filename)


    def update(self, filename, oldhash, filehash):
        self.op_queue.append([filename, oldhash, filehash])
    #
    # This is called when a client has a file changed
    #
    def call_update(self, filename, oldhash, filehash):
        fn = filename.replace("%sep%", os.sep)
        #create a push packet
        packet = {
            "type": "push",
            "name": filename,
            "size": os.path.getsize(fn),
            "hash": oldhash
        }
        self.client_s.sendall(json.dumps(packet))
        d = self.client_s.recv(1024)
        response = json.loads(d)
        #make sure that the server wants the packet, our old hash must match
        #the servers hash for the server to accept our file
        if response["type"] == "send":
            #open the file read send it 1024 bytes at a time
            f = self.fm.open_file(filename, "rb")
            while 1:
                data = f.read(1024)
                if not data: break
                self.client_s.sendall(data)
            self.fm.close_file(filename, f)
        else:
            #print response["error"]
            pass


    def get_file(self, filename):
        base_req = {
            "type": "request",
            "name": ""
        }
        #if not we need to download it, so prepare the request
        base_req["name"] = filename
        #send the request
        self.client_s.sendall(json.dumps(base_req))
        #get the response
        data = self.client_s.recv(1024)
        message = json.loads(data)
        #if we get to download the file
        if message["type"] == "download":
            #get the expected size
            size = int(message["size"])
            data = ''
            downloaded = 0
            #open the local file
            f = self.fm.open_file(filename, "wb")
            print "Downloading:", filename.replace("%sep%", os.sep)
            #let the server know we are ready
            self.client_s.sendall('r')
            #while there is more file
            while downloaded < size:
                # get the next chunk
                data = self.client_s.recv(1024)
                # keep track of how much we have
                downloaded += len(data)
                #write it to the file
                f.write(data)
                progress = int(float(downloaded)/size*100)
                print progress,
                sys.stdout.flush()
            print
            #we are done so close the file
            #self.fm.update_hash(filename)
            self.fm.close_file(filename, f)
        else:
            print message
            print message["error"]
