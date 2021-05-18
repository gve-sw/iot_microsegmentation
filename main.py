'''
Copyright (c) 2021 Cisco and/or its affiliates.

This software is licensed to you under the terms of the Cisco Sample
Code License, Version 1.1 (the "License"). You may obtain a copy of the
License at

               https://developer.cisco.com/docs/licenses

All use of the material herein must be in accordance with the terms of
the License. All rights not expressly granted by the License are
reserved. Unless required by applicable law or agreed to separately in
writing, software distributed under the License is distributed on an "AS
IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
or implied.
'''


import requests, yaml, json
from flask import Flask, render_template, request, url_for, json, redirect
from netmiko import ConnectHandler

# get credentials
config = yaml.safe_load(open("credentials.yml"))
ISE_instance = config['ISE_instance']
ISE_username = config['ISE_username']
ISE_password = config['ISE_password']
switch_ssh_username = config['switch_ssh_username']
switch_ssh_password = config['switch_ssh_password']
switch_ssh_enable_password = config['switch_ssh_enable_password']
sxpSwitch_list = []
connected_endpoints = []
endpoint_details = {}
select_maintenance = 'false'
redirecting = False

# flask app
app = Flask(__name__)

# base URL
base_url = 'https://' + ISE_instance + ':9060/ers/config/'
headers = {
    'Accept': 'application/json'
}
auth = (ISE_username, ISE_password)
redirect_ISE = 'https://' + str(ISE_instance)

@app.route('/',methods=['GET','POST'])
def index():
    return redirect(url_for('.microsegment'))


# STEP 1: select the switch based from the list of SXP switches in ISE
@app.route('/microsegment',methods=['GET','POST'])
def microsegment():
    global sxpSwitch_list
    global connected_endpoints
    global endpoint_details
    global select_maintenance

    sxpSwitch_list = []
    connected_endpoints = []
    endpoint_details = {}
    select_maintenance = 'false'
    logic = 0
    alert = 0

    get_SXP_switches = requests.get(base_url + 'sxpconnections', headers=headers, auth=auth, verify=False)

    for item in get_SXP_switches.json()['SearchResult']['resources']:
        id = item['id']
        get_SXP_switch_byID = requests.get(base_url + 'sxpconnections/' + id, headers=headers, auth=auth, verify=False)
        sxpSwitch = get_SXP_switch_byID.json()['ERSSxpConnection']['sxpPeer']
        sxpSwitch_list.append(sxpSwitch)

    sxpSwitch_list = list(dict.fromkeys(sxpSwitch_list))

    return render_template("microsegment.html",redirect_ISE=redirect_ISE,switches=sxpSwitch_list,endpoints=connected_endpoints,endpoint_details=endpoint_details,logic=logic,select_maintenance=select_maintenance,alert=alert)


@app.route('/submit_switch', methods=['POST'])
def submit_switch():
    global redirecting
    redirecting = False
    req = request.form
    selected_switch = req['switch']
    return redirect(url_for('endpoint',selected_switch=selected_switch))


# STEP 2: retrieve list of endpoints connected to the switch, e.g. with sh device-tracking database
@app.route('/microsegment/<selected_switch>', methods=['GET'])
def endpoint(selected_switch):
    global sxpSwitch_list
    global connected_endpoints
    global endpoint_details
    global select_maintenance
    global redirecting

    logic = 0
    alert = 0
    if redirecting == True:
        alert = 1

    try:
        selected_ip_id = requests.get(base_url + 'networkdevice/?filter=name.CONTAINS.' + selected_switch, headers=headers, auth=auth,
                         verify=False).json()['SearchResult']['resources'][0]['id']
        selected_ip = requests.get(base_url + 'networkdevice/' + selected_ip_id, headers=headers, auth=auth,
                         verify=False).json()['NetworkDevice']['NetworkDeviceIPList'][0]['ipaddress']
        ch = ConnectHandler(device_type='cisco_ios', host=selected_ip, username=switch_ssh_username, password=switch_ssh_password, secret=switch_ssh_enable_password)
        print('connected')
        ch.enable()
        output = ch.send_command('sh device-tracking database')
        output_list = [y for y in (x.strip() for x in output.splitlines()) if y]
        connected_endpoints = []
        for output_line in output_list:
            if output_line.startswith('L'):
                sort = output_line.split()
                format_mac = sort[2].replace('.', '')
                formatted_mac = ':'.join([format_mac[i:i+2] for i in range(0, len(format_mac), 2)])
                output_sorted = {
                    'ip': sort[1],
                    'mac': formatted_mac
                }
                connected_endpoints.append(output_sorted)
        sxpSwitch_list = [selected_switch]
        logic = 1
    except:
        print('could not connect')
        alert = 1

    return render_template("microsegment.html",redirect_ISE=redirect_ISE,switches=sxpSwitch_list,endpoints=connected_endpoints,endpoint_details=endpoint_details,logic=logic,select_maintenance=select_maintenance,alert=alert)


# STEP 3: select on IP address of the list
@app.route('/submit_endpoint', methods=['POST'])
def submit_endpoint():
    req = request.form
    selected_endpoint = req['endpoint']
    return redirect(url_for('endpoint_description',selected_switch=sxpSwitch_list[0],selected_endpoint=selected_endpoint))


# STEP 4: ask ISE to get more info on what is the IP (description, endpoint policy)
@app.route('/microsegment/<selected_switch>/<selected_endpoint>', methods=['GET'])
def endpoint_description(selected_switch, selected_endpoint):
    global sxpSwitch_list
    global connected_endpoints
    global endpoint_details
    global select_maintenance

    alert = 0
    logic = 2


    for connected in connected_endpoints:
        if connected['ip'] == selected_endpoint:
            endpoint = connected['mac']
            break

    try:
        get_endpoint_details = requests.get(base_url + 'endpoint/?filter=mac.CONTAINS.' + endpoint, headers=headers,
                                            auth=auth, verify=False)

        endpoint_id = get_endpoint_details.json()['SearchResult']['resources'][0]['id']
        endpoint_details_ = requests.get(base_url + 'endpoint/' + endpoint_id, headers=headers, auth=auth, verify=False).json()['ERSEndPoint']
        endpointprofile = requests.get(base_url + 'profilerprofile/' + endpoint_details_['profileId'], headers=headers, auth=auth, verify=False).json()['ProfilerProfile']['name']
        identitygroupassignment = requests.get(base_url + 'endpointgroup/' + endpoint_details_['groupId'], headers=headers, auth=auth, verify=False).json()['EndPointGroup']['name']
        try:
            description = endpoint_details_['description']
        except:
            description = ''

        endpoint_details = {
            'selected_endpoint': selected_endpoint, # equals ip
            'id': endpoint_details_['id'],
            'name': endpoint_details_['name'],
            'mac': endpoint_details_['mac'],
            'username': endpoint_details_['portalUser'],
            'description': description,
            'staticassignment': str(endpoint_details_['staticProfileAssignment']),
            'endpointprofile': endpointprofile,
            'staticgroupassignment': str(endpoint_details_['staticGroupAssignment']),
            'identitygroupassignment': identitygroupassignment,
            'assetProjectName': endpoint_details_['customAttributes']['customAttributes']['assetProjectName']
        }

        if endpoint_details['assetProjectName'] == '':
            select_maintenance = 'true'
        else:
            select_maintenance = 'false'

        connected_endpoints = [{'ip': selected_endpoint, 'mac': endpoint_details['mac']}]

        return render_template("microsegment.html", redirect_ISE=redirect_ISE, switches=sxpSwitch_list,
                               endpoints=connected_endpoints, endpoint_details=endpoint_details, logic=logic,
                               select_maintenance=select_maintenance, alert=alert)
    except:
        global redirecting
        redirecting = True
        return redirect(url_for('endpoint', selected_switch=selected_switch))



# STEP 5: modify assetProjectName value to Maintenance
@app.route('/submit_maintenance', methods=['POST'])
def submit_maintenance():
    global endpoint_details
    selected_endpoint = endpoint_details['selected_endpoint']

    req = request.form

    # STEP 6: modification is sent to ISE in pxgrid with a value
    data = {
        'ERSEndPoint': {
            'customAttributes': {
                'customAttributes': {
                    'assetProjectName': 'maintenance'
                }
            }
        }
    }
    if 'undo_maintenance' in req:
        data['ERSEndPoint']['customAttributes']['customAttributes']['assetProjectName'] =  ''

    headers['Content-Type'] = 'application/json'
    update_customAttribute = requests.put(base_url + 'endpoint/' + endpoint_details['id'], headers=headers,
                                    auth=auth, data=json.dumps(data), verify=False)

    return redirect(url_for('endpoint_description',selected_switch=sxpSwitch_list[0],selected_endpoint=selected_endpoint))



if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5001, debug=True, threaded=True)