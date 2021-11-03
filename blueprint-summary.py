import requests
import aiohttp
import yaml
from yaml.loader import SafeLoader
import asyncio
import csv
import sys
import bwl_utils
import time
import logging
import argparse
from tqdm import tqdm


parser = argparse.ArgumentParser()
parser.add_argument("-c", "--config", help="config file name")
args = parser.parse_args()
config_filename = args.config

if config_filename is None:
    # Default config filename
    config_filename = "config.yaml"

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s')
file_handler = logging.FileHandler('bwl-util.log')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)
logger.setLevel(logging.DEBUG)

# Load the config
try:
    with open(config_filename, 'r') as config_file:
        config = yaml.load(config_file, Loader=SafeLoader)
except FileNotFoundError as e:
    msg = "Cannot find config file : config.yaml or the config file specified in arguments"
    print(msg)
    logger.error(msg)
    sys.exit("BWL API Util - aborting.")


start_time = time.time()
logger.info('Starting')
# Get config for blueworks live URL, client_id and client_secret
ROOT_URL = config['root-url']
AUTH_URL = ROOT_URL + "/oauth/token"
CLIENT_REPORTING_ID = config['artefact-reporting-client-id']
CLIENT_REPORTING_SECRET = config['artefact-reporting-client-secret']


AUTH_DATA = {
    'grant_type': 'client_credentials',
    'client_id': CLIENT_REPORTING_ID,
    'client_secret': CLIENT_REPORTING_SECRET
}

# Get the access token here
try:
    response = requests.post(AUTH_URL, data=AUTH_DATA)
    access_token = response.json()['access_token']
    if not access_token:
        raise ValueError('Access token could not be retrieved, please check your input')
except ValueError as e:
    logger.warning(e)
    print(e)
    exit()

print(f"Access Token : {access_token}")

BLUEPRINT_LIB_URL = ROOT_URL + "/scr/api/LibraryArtifact?type=BLUEPRINT&returnFields=ID"
head = {
    'Authorization': 'Bearer {}'.format(access_token)
    # 'X-On-Behalf-Of' : 'mark_ketteman@uk.ibm.com'
}
blueprint_lib_response = requests.get(BLUEPRINT_LIB_URL, headers=head).text
blueprint_list = blueprint_lib_response.split('\n')

#remove the first element
blueprint_list = blueprint_list[1:-1]

print(f"Found {len(blueprint_list)} blueprints")

#Create lists for the output
bp_export = []
bp_errors = []


async def main():
    connector = aiohttp.TCPConnector(limit=5)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = []
        pbar = tqdm(total=len(blueprint_list))
        for bp_id in blueprint_list:
            bp_id = bp_id.strip('/"')
            task = asyncio.ensure_future(get_blueprint_data(session, bp_id, pbar))
            tasks.append(task)

        await asyncio.gather(*tasks)
        pbar.close()

async def get_blueprint_data(session, bp_id, pbar):
    bp_url = ROOT_URL + "/bwl/blueprints/" + bp_id

    async with session.get(bp_url, headers=head, ssl=False) as response:
        try:
            status = response.status
            if status == 200:
                bp_json = await response.json()
                bp_name = bwl_utils.get_name(bp_json)
                space_name = bwl_utils.get_space_name(bp_json)
                lmd = bwl_utils.get_last_modified_date(bp_json)
                age = bwl_utils.get_age(bp_json)

                bp_record = {'ID': bp_id, 'name': bp_name, 'space': space_name, 'last-modified': lmd, 'age': age}
                bp_export.append(bp_record)

                message = f"Finished processing blueprint ID : {bp_id}, Space : {space_name}, Name : {bp_name}"
                logger.debug(message)
                pbar.update(1)
            else:
                message = f"Error processing blueprint : {bp_id}, response code from BWL : {status}"
                logger.warning(message)
                bp_error = {'ID': bp_id}
                bp_errors.append(bp_error)
                pbar.update(1)

        except Exception as e:
            bp_error = {'ID': bp_id}
            bp_errors.append(bp_error)
            message = f"Unexpected error processing blueprint : {bp_id}"
            logger.error(message)
            logger.error(e)

asyncio.run(main())

# Save the data
data_file = open('data_file.csv', 'w')

# Standard headers
header = ['ID', 'Name', 'Space', 'LMD', 'Age in Days']
csv_writer = csv.writer(data_file)
row_count = 0
for bp_record in bp_export:
    if row_count == 0:
        csv_writer.writerow(header)
        row_count += 1

    csv_writer.writerow(bp_record.values())

data_file.close()

#Save any errors
error_file = open('error_file.csv', 'w')
header = ['ID']
csv_writer = csv.writer(error_file)
row_count = 0
for bp_record in bp_errors:
    if row_count == 0:
        csv_writer.writerow(header)
        row_count += 1

    csv_writer.writerow(bp_record.values())

error_file.close()


print("--- %s seconds ---" % (time.time() - start_time))
logger.info('Finished')