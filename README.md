My proposed project is a server-client file syncing application. Clients would provide an IP port a group name and a password.  The server would then keep the files synced between all clients and the server. 

The server:
creates a hash for every file in the directory and then waits for clients and changes to files in the directory. This would probably be done with one thread waiting for new changes to files and one thread waiting for clients.
When a client connects they would authenticate by sending:

```
{
    “type”: “auth”,
    “group”: group_name
    “hash”:sha1(group_name+password)
}
```
if the password is correct they will be added to a client list. otherwise the connection will be closed
All files on new connected clients are to be considered older than the current server version.
When a file in the directory is changed a new hash is created and request attempted to be sent to all clients of the format:
```
{
    “type”: “update”,
    “name”: “filename”,
    “old”: [old hash of file],
    “new”: [new hash of file]
}
```

if the packet could not be sent the client is removed from the list
Server can respond to requests for the file by sending:

```
{
    “type”: “download”,
    “size”: [file size],
    “name”: [filename]
}
```

followed by 1000 byte packets containing the file
The server can receive packets of the form:

```
{
    “type”: “push”,
    “name”: [filename],
    “size”: filesize,
    “hash”: [hash that matches the version on the server]
}
```


if the hash matches the server version for that file the server will respond with:

```
{
    “type”:”accept”
}
```

and the client will upload the file with packets of 1000 bytes each

The client:
Clients can make a request for any file using its filename and hash of the format:

```
{
    “type”: “request”
    “hash”: [hash]
}
```

Clients wait for changes to the files in the directory and once a change is made it starts a 1 minute timer. Anytime the same file is edited it restarts the timer. When the timer expires the client pushes to the server(see above)
