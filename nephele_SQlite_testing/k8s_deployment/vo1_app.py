#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging

from wotpy.functions.functions import vo_status, device_status

LOGGER = logging.getLogger()

TABLE_NAME = "string_data_table"


async def someStringProperty_write_handler(value):
    servient = exposed_thing.servient
    sqlite_db = servient.sqlite_db
    filename = value["filename"]
    content = value["content"]

    columns = {
        "filename": "TEXT",
        "content": "TEXT"
    }
    sqlite_db.create_table_if_not_exists(TABLE_NAME, columns)
    sqlite_db.insert_data(TABLE_NAME, (filename, content))

async def map_write_handler(value):
    servient = exposed_thing.servient
    sqlite_db = servient.sqlite_db
    filename = value["filename"]
    content = value["content"]

    columns = {
        "filename": "TEXT",
        "content": "TEXT"
    }
    sqlite_db.create_table_if_not_exists(TABLE_NAME, columns)
    sqlite_db.insert_data(TABLE_NAME, (filename, content))

async def someStringProperty_read_handler():
    servient = exposed_thing.servient
    sqlite_db = servient.sqlite_db

    return servient.sqlite_db.execute_query("SELECT content FROM string_data_table WHERE filename='filename2'")
    #return servient.sqlite_db.fetch_all_rows(TABLE_NAME)
    
async def filenamesReadDB_handler(params):
    params = params['input'] if params['input'] else {}
    # Default values
    servient = exposed_thing.servient
    sqlite_db = servient.sqlite_db
    result=sqlite_db.execute_query("SELECT filename FROM string_data_table")
    return result

async def mapReadDB_handler(params):
    params = params['input'] if params['input'] else {}
    # Default values
    filename_map = 'test'
    filename_map = params.get('filename_map', filename_map)
    LOGGER.info('Result after params is {}'.format(filename_map))
    servient = exposed_thing.servient
    sqlite_db = servient.sqlite_db
    result=sqlite_db.execute_query("SELECT content FROM string_data_table WHERE filename='%s'" % filename_map)
   # result= sqlite_db.execute_query("SELECT filename FROM string_data_table") 
    parsed_result=result[0][0]
    return parsed_result


async def mapStoreDB_handler(params):
    params = params['input'] if params['input'] else {}
     # Default values
    filename_tosave = 'map1'

    # Check if params are provided
    filename_tosave = params.get('filename_tosave', filename_tosave)
    LOGGER.info('Consumed Thing: {}'.format(consumed_vos["tb2"]))
    mapstring = await consumed_vos["tb2"].invoke_action("mapExport")
            
    servient = exposed_thing.servient
    sqlite_db = servient.sqlite_db
    content = mapstring

    columns = {
        "filename": "TEXT",
        "content": "TEXT"
    }
    sqlite_db.create_table_if_not_exists(TABLE_NAME, columns)
    result=sqlite_db.insert_data(TABLE_NAME, (filename_tosave, content))
    
    return {'message': f'Your map storing on db is in progress!'}


async def read_property_from_tb2():
    # Initialize the property values
    allAvailableResources = await consumed_vos["tb2"].properties['allAvailableResources'].read()
    possibleLaunchfiles = await consumed_vos["tb2"].properties['possibleLaunchfiles'].read()
    
    # Initialize the property values
    await exposed_thing.properties['allAvailableResources'].write(allAvailableResources)
    await exposed_thing.properties['possibleLaunchfiles'].write(possibleLaunchfiles)


