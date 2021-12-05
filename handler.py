import os
import requests
import time
import boto3
import uuid

from json import loads, dumps
from requests.auth import HTTPBasicAuth
from json import dumps, loads
from datetime import datetime
    
# Globar parameters
headers = {"Content-type": "application/json", "Accept": "application/json"}

# Account credentials
boomi_account_id = os.environ["BOOMI_ACCOUNT_ID"]
boomi_username = os.environ["BOOMI_USERNAME"]
boomi_api_token = os.environ["BOOMI_API_TOKEN"]

# Boomi environment id
boomi_environments = {
    "DEV": {
        "environmentId": os.environ["DEV_ENV_ID"]
    },
    "QAT": {
        "environmentId": os.environ["QAT_ENV_ID"]
    },
    "PROD": {
        "environmentId": os.environ["PRD_ENV_ID"]
    }
}

# Boomi AtomSphere API Endpoints
boomi_atom_sphere_api_endpoint = os.environ["BOOMI_API_ENDPOINT"]
boomi_component_meta_endpoint = "{}/{}/{}".format(boomi_atom_sphere_api_endpoint, boomi_account_id, "ComponentMetadata/query")
boomi_component_meta_more_endpoint = "{}/{}/{}".format(boomi_atom_sphere_api_endpoint, boomi_account_id, "ComponentMetadata/queryMore")
boomi_environment_endpoint = "{}/{}/{}".format(boomi_atom_sphere_api_endpoint, boomi_account_id, "Environment/query")
boomi_deploy_package_query_endpoint = "{}/{}/{}".format(boomi_atom_sphere_api_endpoint, boomi_account_id, "DeployedPackage/query")
boomi_deploy_package_endpoint = "{}/{}/{}".format(boomi_atom_sphere_api_endpoint, boomi_account_id, "DeployedPackage/")

class Error(Exception):
    """Base-class for all exceptions raised by this module"""
    
class ValueError(Error):
    """Base-class for value errors"""
    
class ConnectionError(Error):
    """Base-class for connection to Boomi AtomSphere API errors, especially for those not 2xx HTTP Response Status"""
    
def get_result(event, context):
    token = ""
    
    # Get input parameter
    if event.get("pathParameters") and event.get("pathParameters").get("token"):
        token = event.get("pathParameters").get("token")
    else:
        return {"statusCode": 400, "body": "Missing Token", "headers": {"Content-Type": "text/plain"}}
        
    # Get result from DynamoDB
    client = boto3.client('dynamodb')    
    response = client.get_item(
                        TableName="boomi-cd-table",
                        Key={
                            "token": {
                                'S': token
                                }
                            })
    
    if response.get("Item"):
        
        if response.get("Item").get("process_status").get("S") == "IN PROGRESS":
            data = {
                "token": token,
                "input": loads(response.get("Item").get("input").get("S")),
                "status": response.get("Item").get("process_status").get("S")
            }
        else:
            data = {
                "token": token,
                "input": loads(response.get("Item").get("input").get("S")),
                "status": response.get("Item").get("process_status").get("S"),
                "component": loads(response.get("Item").get("component").get("S"))
            }
    else: 
        return {"statusCode": 400, "body": {"message": "Incorrect Token"}}
                            
    return {"statusCode": 200, "body": dumps(data, indent=2)}
    
def deploy(event, context):
    
    # Get input parameter
    input_parameter = loads(event.get("body"))
    
    # Validate input parameter and environment
    try:
        validate_input_parameter(input_parameter)
    except ValueError as ve:
        return {"statusCode": 400, "body": str(ve), "headers": {"Content-Type": "text/plain"}}
    except ConnectionError as ce:
        return {"statusCode": 500, "body": str(ce), "headers": {"Content-Type": "text/plain"}}
    except Exception as e:
        return {"statusCode": 500, "body": "Process Error", "headers": {"Content-Type": "text/plain"}}
    
    # Generate token and set into input_parameter for next process
    token = str(uuid.uuid4())
    input_parameter['token'] = token
    
    # Create a new record in DynamoDB
    client = boto3.client("dynamodb")
    response = client.put_item(
                        TableName="boomi-cd-table",
                        Item={
                            "token": {
                                "S": token
                            },
                            "process_status": {
                                "S": "IN PROGRESS"
                            },
                            "input": {
                                "S": dumps(input_parameter)
                            }
                        })
                        
    # Push input parameter to SQS
    client = boto3.client('sqs')
    response = client.send_message(QueueUrl=os.environ["SQS_QUEUE_URL"], MessageBody=dumps(input_parameter))
    
    # return token
    return {"statusCode": 200, "body": dumps({"token": token})}
    
    
def process_deployment(event, context):
    
    # Get input parameter
    input_parameter = loads(event.get("Records")[0].get("body"))
    
    print("Process deployment : {}".format(event))
        
    # Set required values to local variables
    token = input_parameter.get("token")
    env_source = input_parameter.get('environment').get('source')
    env_destination = input_parameter.get('environment').get('destination')
    projects = input_parameter.get('projects')
    notes = input_parameter.get('notes')
    
    # Populate component detail
    list_component = populate_component(projects)
    
    # Get Package ID for all components
    # list_component = populate_packageId(env_source, list_component)
    populate_packageId(env_source, list_component)
    
    # Deploy package to destination environment
    # list_component = deploy_package(env_destination, list_component, notes)
    print("Number of component in list = {}".format(len(list_component)))
    deploy_package(env_destination, list_component, notes)
    
    # Create a new record in DynamoDB
    client = boto3.client("dynamodb")
    response = client.update_item(
                                TableName="boomi-cd-table",
                                Key={
                                    "token": {
                                        "S": token
                                        
                                    }
                                },
                                UpdateExpression="set component = :val1, process_status = :val2",
                                ExpressionAttributeValues={
                                    ":val1": {
                                        "S": dumps(list_component)
                                        
                                    },
                                    ":val2": {
                                        "S": "DONE"
                                    }
                                },
                                ReturnValues="UPDATED_NEW"
                            )
        
    return {"statusCode": 200, "body": "Success", "Content-Type":"text/plain"}
    
def deploy_package(env_destination, list_component, notes):
    
    now = datetime.now()
    dt_string = now.strftime("%d/%m/%Y %H:%M:%S")
    notes = "{} - {} ".format(dt_string, notes)
    print("Number of component to be deployed = {}".format(len(list_component)))
    for item in list_component:
        
        id = item.get("packageId")
        name = item.get("name")
        
        payload = { "environmentId" : boomi_environments[env_destination]['environmentId'],
                    "packageId" : id,
                    "notes" : notes
                }
        print("{} to {} :: payload: {}".format(name, env_destination, payload))
    
        response = requests.post(boomi_deploy_package_endpoint, 
                             headers=headers, 
                             auth=HTTPBasicAuth(boomi_username, boomi_api_token), 
                             data=dumps(payload))
        
        if response.status_code == 200:
            item["status"] = "DEPLOYED"
            print("{} :: Id: {} is DEPLOYED.".format(name, id))
        elif response.status_code == 400:
            item["status"] = "EXISTING"
            print("{} :: Id: {} is use existing.".format(name, id))
        else:
            item["status"] = "ERROR"
            item["errorMessage"] = response.text
            print("{} :: Id: {} encounter error {}.".format(name, id, response.text))
            
        time.sleep(1)
            
    return list_component
    
def populate_packageId(env_source, list_component):
    
    for item in list_component:
        
        id = item.get("componentId")
        name = item.get("name")
        
        payload = {
            "QueryFilter": {
                "expression": {
                    "operator": "and",
                    "nestedExpression": [
                        {
                            "argument": [
                                id
                            ],
                            "operator": "EQUALS",
                            "property": "componentId"
                        },
                        {
                            "argument": [
                                boomi_environments[env_source]['environmentId']
                            ],
                            "operator": "EQUALS",
                            "property": "environmentId"
                        },
                        {
                            "argument": [
                                True
                            ],
                            "operator": "EQUALS",
                            "property": "active"
                        }
                    ]
                }
            }
        }
        
        response = requests.post(boomi_deploy_package_query_endpoint, 
                             headers=headers, 
                             auth=HTTPBasicAuth(boomi_username, boomi_api_token), 
                             data=dumps(payload))
        
        if response and response.text:
            resp_body = loads(response.text)
        
            if resp_body and resp_body.get('result') and len(resp_body.get('result')) > 0:
                packageId = resp_body.get('result')[0]['packageId']
                item["packageId"] = packageId
                print("{} :: componentId: {} :: packageId: {}".format(name, id, packageId))
            else:
                print("{} :: componentId: {} :: packageId: N/A".format(name, id))
        else:
            print("{} :: Invalid Response: {} - {}".format(name, response, response.text))
            
        time.sleep(1)
            
    # return list_component
    
def populate_component(projects):
    list_component = []

    for item in projects:
        payload = {
            "QueryFilter": {
                "expression": {
                    "operator": "and",
                    "nestedExpression": [
                        {
                            "argument": [
                                "{}%".format(item.get("componentPrefix"))
                            ],
                            "operator": "LIKE",
                            "property": "name"
                        },
                        {
                            "argument": [
                                item.get("projectName")
                            ],
                            "operator": "EQUALS",
                            "property": "folderName"
                        },
                        {
                            "argument": [
                                False
                            ],
                            "operator": "EQUALS",
                            "property": "deleted"
                        },
                        {
                            "argument": [
                                True
                            ],
                            "operator": "EQUALS",
                            "property": "currentVersion"
                        }
                    ]
                }
            }
        }
        
        response = requests.post(boomi_component_meta_endpoint, 
                             headers=headers, 
                             auth=HTTPBasicAuth(boomi_username, boomi_api_token), 
                             data=dumps(payload))
    
        resp_body = loads(response.text)
        if resp_body.get('queryToken'):
            query_token = resp_body['queryToken'] 
        else:
            query_token = None
                
        print("Number of total records in result : {}".format(resp_body['numberOfResults']))
        list_component.extend(resp_body['result'])
    
        has_next = False
    
        if query_token:
            has_next = True
    
        while (has_next):
            payload = query_token
            response = requests.post(boomi_component_meta_more_endpoint, 
                                 headers=headers, 
                                 auth=HTTPBasicAuth(boomi_username, boomi_api_token), 
                                 data=query_token)
            resp_body = loads(response.text)
    
            if resp_body.get('queryToken'):
                query_token = resp_body['queryToken'] 
            else:
                query_token = None
    
            list_component.extend(resp_body['result'])
    
            if query_token:
                continue
            else:
                has_next = False
                
    print("Number of total records in list : {}".format(len(list_component)))
    return list_component
    
def verify_environment(environment_id):
    is_valid = False
    
    payload = {
      "QueryFilter" :
        {
          "expression" :
            {
              "argument" : [environment_id],
              "operator" : "EQUALS",
              "property" : "id"
            }
        }
    }

    response = requests.post(boomi_environment_endpoint, 
                             headers=headers, 
                             auth=HTTPBasicAuth(boomi_username, boomi_api_token), 
                             data=dumps(payload))

    if response.status_code == 200:
        response_body = loads(response.text)
        
        if response_body.get("result"):
            if response_body.get("result")[0]['id']:
                is_valid = True
    else:
        raise ConnectionError("Response from Boomi AtomSphereAPI : {}\nError message: {}".format(response.status_code, response.text))

    
def validate_input_parameter(input_parameter):
    # Check if input_parameter is available
    if input_parameter is None:
        raise ValueError("Error: Missing input parameter")
        
    # Check if environment (source and destination) is available
    if input_parameter.get("environment") is None:
        raise ValueError("Error: Environment is mandatory")
    else:
        environment = input_parameter.get("environment")
        
        if environment.get("source") is None:
            raise ValueError("Error: Source Environment is mandatory")
        
        if environment.get("destination") is None:
            raise ValueError("Error: Destination Environment is mandatory")
            
    # Check if projects is available
    if input_parameter.get("projects") is None:
        raise ValueError("Error: Projects is mandatory")
    else:
        projects = input_parameter.get("projects")
        
        if len(projects) == 0:
            raise ValueError("Error: Projects must have at least one project")
            
    # Check value of source and destination environments
    available_env = list(boomi_environments.keys())
    available_source = ["DEV", "QAT"]
    available_destination = ["QAT", "PROD"]
    
    if input_parameter.get("environment").get('source') not in available_env:    
        raise ValueError("Error: Source environment is not available")
        
    if input_parameter.get("environment").get('destination') not in available_env:    
        raise ValueError("Error: Destination environment is not available")
        
    if input_parameter.get("environment").get('source') == input_parameter.get("environment").get('destination'):
        raise ValueError("Error: Source and Destination environment cannot be same value")
        
    if input_parameter.get("environment").get('source') not in available_source:    
        raise ValueError("Error: Source environment is only available for DEV and QAT")
        
    if input_parameter.get("environment").get('destination') not in available_destination:    
        raise ValueError("Error: Destination environment is only available for QAT and PROD")
    
    # Check project name and component prefix
    for project in projects:
        if project.get('projectName') is None:
            raise ValueError("Error: Project Name is mandatory")
            
        if project.get('componentPrefix') is None:
            raise ValueError("Error: Component Prefix is mandatory")

    env_source = input_parameter.get('environment').get('source')
    verify_environment(boomi_environments[env_source]["environmentId"])
    
    env_destination = input_parameter.get('environment').get('destination')
    verify_environment(boomi_environments[env_destination]["environmentId"])