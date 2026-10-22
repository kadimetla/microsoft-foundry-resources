// Workshop MCP server infrastructure (iteration 1).
//
// Provisions:
//   - Storage account (required by Functions + by the MCP extension's queues)
//   - Application Insights (optional: reuses an existing one if you pass its
//     connection string, so KQL queries can correlate across the Foundry agent
//     and this Function App)
//   - Flex Consumption Function App (FC1) running Python 3.13
//
// Run via `azd up` from `06-weather-mcp-agent/mcp-server`.

targetScope = 'resourceGroup'

@minLength(1)
@maxLength(20)
@description('Suffix appended to resource names. Defaults to a short hash of the resource group id.')
param namePrefix string = 'wxmcp${uniqueString(resourceGroup().id)}'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Foundry project Application Insights connection string. Paste the same value used by 02-mcp-tool-agent.py so the KQL cookbook can correlate spans. Leave blank to create a new App Insights resource.')
@secure()
param existingApplicationInsightsConnectionString string = ''

// -- Iteration 2: Microsoft Entra / Easy Auth ---------------------------------
// Provide these to lock the Function App behind Entra (Easy Auth v2 + Anonymous
// webhook auth level). When ``entraAppId`` is empty Bicep skips ``authsettingsV2``
// entirely so iteration 1 (function-key only) behaviour is preserved. The
// ``api://<appId>`` audience is added automatically; provide ``entraExtraAudiences``
// for any additional accepted ``aud`` values.

@description('Entra application (client) ID protecting this Function App. Leave blank to disable Easy Auth (iteration 1).')
param entraAppId string = ''

@description('Entra tenant ID hosting the app registration. Defaults to the deploying subscription tenant.')
param entraTenantId string = subscription().tenantId

@description('Extra audiences to accept in addition to ``api://<entraAppId>`` and ``<entraAppId>``.')
param entraExtraAudiences array = []

@description('Tags applied to every resource.')
param tags object = {
  'azd-env-name': namePrefix
  workshop: 'msft-foundry'
  sample: '06-weather-mcp-agent'
}

var storageAccountName = toLower(replace('${namePrefix}stor', '-', ''))
var planName = '${namePrefix}-plan'
var functionAppName = '${namePrefix}-func'
var workspaceName = '${namePrefix}-law'
var appInsightsName = '${namePrefix}-ai'
var deploymentStorageContainerName = 'app-package-${functionAppName}'
var createNewAppInsights = empty(existingApplicationInsightsConnectionString)

// -- Storage -----------------------------------------------------------------
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource deploymentContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: deploymentStorageContainerName
  properties: { publicAccess: 'None' }
}

// -- Optional new App Insights -----------------------------------------------
resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = if (createNewAppInsights) {
  name: workspaceName
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = if (createNewAppInsights) {
  name: appInsightsName
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
    DisableLocalAuth: false
  }
}

var resolvedAiConnectionString = createNewAppInsights
  ? appInsights.properties.ConnectionString
  : existingApplicationInsightsConnectionString

// -- Flex Consumption plan ---------------------------------------------------
resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: planName
  location: location
  tags: tags
  kind: 'functionapp,linux'
  sku: {
    name: 'FC1'
    tier: 'FlexConsumption'
  }
  properties: {
    reserved: true
  }
}

// -- Function App ------------------------------------------------------------
resource functionApp 'Microsoft.Web/sites@2024-04-01' = {
  name: functionAppName
  location: location
  // The `azd-service-name: api` tag is REQUIRED so `azd deploy` knows which
  // resource maps to the `api` service in azure.yaml. Merged with the common
  // workshop tags via union().
  tags: union(tags, { 'azd-service-name': 'api' })
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storage.properties.primaryEndpoints.blob}${deploymentStorageContainerName}'
          authentication: { type: 'SystemAssignedIdentity' }
        }
      }
      scaleAndConcurrency: {
        maximumInstanceCount: 40
        instanceMemoryMB: 2048
      }
      runtime: {
        name: 'python'
        version: '3.13'
      }
    }
    siteConfig: {
      appSettings: [
        {
          name: 'AzureWebJobsStorage__accountName'
          value: storage.name
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: resolvedAiConnectionString
        }
        {
          name: 'APPLICATIONINSIGHTS_ENABLE_AGENT'
          value: 'true'
        }
        {
          name: 'OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_REQUEST'
          value: 'traceparent'
        }
      ]
    }
  }
}

// Grant the Function App's managed identity Storage Blob Data Owner so it can
// publish its own deployment package.
var storageBlobDataOwnerRoleId = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
resource storageBlobOwnerRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, functionApp.id, storageBlobDataOwnerRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataOwnerRoleId)
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Storage Queue Data Contributor — the MCP extension uses queues for its SSE
// transport, so the Function App must be able to read/write queue messages.
var storageQueueDataContributorRoleId = '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
resource storageQueueContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, functionApp.id, storageQueueDataContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageQueueDataContributorRoleId)
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// -- Iteration 2: Easy Auth v2 (only when ``entraAppId`` is set) -------------
// Documented in ``06-weather-mcp-agent/README.md`` Section "Iteration 2".
// ``unauthenticatedClientAction: Return401`` is critical: MCP/SSE clients
// can't follow ``RedirectToLoginPage`` (302) and would break.
// ``requestedAccessTokenVersion: 2`` on the app reg ensures token ``ver`` is
// 2.0, matching the ``/v2.0`` issuer below.
var enableEasyAuth = !empty(entraAppId)
// Foundry portal "Add MCP tool → Microsoft Entra → Agent Identity" appears to
// reject ``api://<guid>`` audiences with ``ARA request failed: BadRequest``.
// The portal's own example is ``https://azconfig.io`` (HTTPS scheme), so we
// also include the Function App's HTTPS hostname as an allowed audience. The
// Entra app reg must also list this URL in ``identifierUris``.
var aadAllowedAudiences = union(
  [
    'api://${entraAppId}'
    entraAppId
    'https://${functionApp.properties.defaultHostName}'
  ],
  entraExtraAudiences
)

resource authSettings 'Microsoft.Web/sites/config@2024-04-01' = if (enableEasyAuth) {
  parent: functionApp
  name: 'authsettingsV2'
  properties: {
    platform: {
      enabled: true
    }
    globalValidation: {
      requireAuthentication: true
      unauthenticatedClientAction: 'Return401'
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          openIdIssuer: 'https://login.microsoftonline.com/${entraTenantId}/v2.0'
          clientId: entraAppId
        }
        validation: {
          allowedAudiences: aadAllowedAudiences
        }
      }
    }
    login: {
      tokenStore: {
        enabled: false
      }
    }
  }
}

// -- Outputs -----------------------------------------------------------------
output FUNCTION_APP_NAME string = functionApp.name
output FUNCTION_APP_HOSTNAME string = functionApp.properties.defaultHostName
output MCP_ENDPOINT string = 'https://${functionApp.properties.defaultHostName}/runtime/webhooks/mcp'
output AZURE_RESOURCE_GROUP string = resourceGroup().name
output APPLICATIONINSIGHTS_CONNECTION_STRING string = resolvedAiConnectionString
output EASY_AUTH_ENABLED bool = enableEasyAuth
