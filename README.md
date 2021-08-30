# Boomi - Continuous Deployment

[Boomi](https://boomi.com) is an integration solution (iPaaS) to easily integrate applications, partners, and customers via the web with a visual designer and a number of pre-configured components. Boomi has a number of exciting functions and tools to create and maintain integration between two or more end-points.

Boomi Integration is ran on Boomi AtomSphere Platform. Boomi AtomSphere Platform has a homepage to easily manageing processes, models, APIs, etc. It also provides programmatic access (Boomi AtomSphere API) to functionality that is normally accessed through the Boomi AtomSphere platform.

This simple application is a simple solution to manage deployment processes in Boomi Integration. Using this application, we can do automate deployment and testing processes.

## Pre-requisites

-   There are three environments used in this solution. Those are
    -   DEV for development environment
    -   QAT for user acceptance testing environment
    -   PROD for production environment
-   This solution deploys Processes and Flow Service components only.

-   Components must have particular prefix. It can follow the project name for example `AdmissionFlowService` as in screenshot below.

![](/images/project_prefix.JPG)

-   Deployment can be done in following scenarios
    -   From DEV to QAT environments
    -   From DEV to PROD environments
    -   From QAT to PROD environments

```
Note:
Integration Developer must have deployed the components into DEV environment manually first before using this application.
```

## Architecture

This application is built using [Serverless Framework](https://serverless.com/) and deployed on [Amazon Web Services](https://aws.amazon.com/) environment.

This is highlevel architecture of this application.

![](/images/architecture_diagram.JPG)

This application has a REST API to receive deployment instruction and trigger the deployment process. `Deployer Lambda` orchestrates deployment process. It will start with payload validation. It validates following items:

-   Source and Destination environment must be valid
-   It contains at least one project for deployment

Once validation process has been passed, it generates a token id that will be used as job id for subsequent process. Before it returns that token id, it stores token id and deployment instruction to database and put token id to queue system.

```
Note:
We use Amazon DynamoDB and Amazon SQS for storage and queue system respectivelly.
```

This event will trigger `Worker Lambda` to pick up job id. Using this job id, this `lambda` will get deployment instruction from database and start to interact with `AtomSphere API`. These are steps done by this `lambda`:

-   Get all components based on project prefix
-   Get components' package id from source environment
-   Deploy components to destination environment

At the end of process, this `lambda` will update job status and put the deployment result in database.

This application has another REST API to get deployment status. It can be pooled till it returns final result or status. The possible status that it returns are:

-   `IN PROGRESS`
    Process is still in progress.
-   `DONE`
    The deployment process is done.

## APIs

These are REST APIs for this application.

| Service           | Method | API                 | Response Status                                |
| ----------------- | ------ | ------------------- | ---------------------------------------------- |
| Deploy components | POST   | /release            | `200` Success<br>`400` Invalid input parameter |
| Get result status | GET    | /release/{token_id} | `200` Success<br>`400` Token error             |

```
Note: For authententication, both APIs require an API Key to be put in header.
```

## Usage

We can use any tools that can send HTTP Request such as `curl`, [Postman](https://www.postman.com/) , [Insomnia](https://insomnia.rest/).

### Deploy components

This is payload that is required for component deployment.

```json
{
    "environment": {
        "source": "DEV",
        "destination": "QAT"
    },
    "projects": [
        {
            "projectName": "Admissions",
            "componentPrefix": "AdmissionFlowService"
        },
        {
            "projectName": "Admissions - Scholarship",
            "componentPrefix": "AdmissionFlowService"
        }
    ],
    "notes": "Deployment"
}
```

| Element                      | Description                                                                               |
| ---------------------------- | ----------------------------------------------------------------------------------------- |
| [environment].[source]       | Source environment. <br>Possible values are either DEV or QAT.                            |
| [environment].[target]       | Destination environment. <br>Possible values are either QAT or PROD.                      |
| [projects]                   | List of project that will be deployed from Source environment to Destination environment. |
| [projects].[projectName]     | Project name.<br>It represents folder name in Boomi Integration Platform.                 |
| [projects].[componentPrefix] | Prefix for components that are deployed to Destination environment.                       |
| [notes]                      | Notes that will be put in deployment description                                          |

This is response after the job has been passed successfully to queue system.

```json
{
    "token": "bf335869-be41-4d2a-a028-94c441ac0678"
}
```

| Element | Description                                                                  |
| ------- | ---------------------------------------------------------------------------- |
| [token] | Unique token id that will be used in subsequent request to get result status |

### Get result status

To get result status, we need to pass token from previous request and put it in query path.

This is a response when deployment process is still in-progress.

```json
{
    "token": "bf335869-be41-4d2a-a028-94c441ac0678",
    "input": {
        "environment": {
            "source": "DEV",
            "destination": "QAT"
        },
        "projects": [
            {
                "projectName": "Admissions",
                "componentPrefix": "AdmissionFlowService"
            },
            {
                "projectName": "Admissions - Scholarship",
                "componentPrefix": "AdmissionFlowService"
            }
        ],
        "notes": "Deployment",
        "token": "bf335869-be41-4d2a-a028-94c441ac0678"
    },
    "status": "IN PROGRESS"
}
```

This is response after deployment process has been done.

```json
{
    "token": "bf335869-be41-4d2a-a028-94c441ac0678",
    "input": {
        "environment": {
            "source": "DEV",
            "destination": "QAT"
        },
        "projects": [
            {
                "projectName": "Admissions",
                "componentPrefix": "AdmissionFlowService"
            },
            {
                "projectName": "Admissions - Scholarship",
                "componentPrefix": "AdmissionFlowService"
            }
        ],
        "notes": "Deployment",
        "token": "bf335869-be41-4d2a-a028-94c441ac0678"
    },
    "status": "DONE",
    "component": [...]
}
```

| Element     | Description                                 |
| ----------- | ------------------------------------------- |
| [token]     | Unique token id that identify a job         |
| [input]     | Requuest payload for this job               |
| [status]    | Deployment Status (`DONE` or `IN PROGRESS`) |
| [component] | List of components                          |

## Future Enhancements

-   In this first release, the application will deploy all-in-one.
    We can enhance it to have capabilities to deploy particular component.

-   It will be good to provide interactive front end so that user can monitor and get real time status for individual component being deployed.
