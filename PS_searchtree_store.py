import os
import time
import dill as pickle
from collections import OrderedDict
import logging
from PS_config import config
from flask import current_app
### Obtaining Mutex from Utils####
from PS_utils import mutex
from time import perf_counter

class PS_SearchTreeStore():
    def __init__(self, maxstoreitems=1):
        self.store = OrderedDict()
        self.maxstoreitems = maxstoreitems

    def __getitem__(self, key):
        searchdbfile = f"./projects/{key}/searchtree_{key}.pkl"
        if not os.path.exists(searchdbfile):
            return None
        modificationTime = time.strftime('%Y-%m-%d %H:%M:%S',
                                         time.localtime(os.path.getmtime(searchdbfile)))
        #### Added Mutex - Zoom Functionality####
        mutex_int = perf_counter()
        with mutex:
            if key not in self.store or self.store[key][1] != modificationTime:
                try:
                    [searchtree, ids] = pickle.load(open(searchdbfile, "rb"))
                    for id, geom in zip(ids, searchtree._geoms):
                        geom.id = int(id)  # https://github.com/Toblerity/Shapely/issues/1033
                    tree = searchtree
                    self.__setitem__(key, [tree, modificationTime])
                    ## Added to move the updated tree to the last entered key
                    self.store.move_to_end(key,last=True)
                    current_app.logger.info(f"SearchTree new: {self.store.keys()}")
                except FileNotFoundError as e:
                    current_app.logger.error(e)
                    return None
            current_app.logger.info(f"SearchTree exists: {self.store.keys()}")
        mutex_exit = perf_counter()
        current_app.logger.info(f"SearchTree_Store mutex: {mutex_exit - mutex_int} seconds")
        return self.store[key][0]

    def __setitem__(self, key, value):
        if len(self.store) >= self.maxstoreitems:
            # Check to not end up with maxstoreitems+1 in memory
            # this prevents others from writing to this and making it bigger unexpectively
            self.store.popitem(last=False) #popitem with last=False uses FIFO and removes first added item in ordereddict.
        self.store[key] = value  # moved the data storage after popitem to end up with right maxstoreitems.


class PS_SearchResultStore():
    def __init__(self, maxstoreitems=1):
        self.store = OrderedDict()
        self.maxstoreitems = maxstoreitems

    def __setitem__(self, key, val):
        if len(self.store) + 1 > self.maxstoreitems:
            self.store.popitem(last=False)
        self.store[key] = val

    def __getitem__(self,key):
        return self.store[key]




SearchResultStore = PS_SearchResultStore(config.getint('caching', 'searchqueries', fallback=5))
SearchTreeStore = PS_SearchTreeStore(config.getint('caching', 'searchtreestorageitems', fallback=1))
