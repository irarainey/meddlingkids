/**
 * @fileoverview OpenAI client configuration and initialization.
 * Supports both Azure OpenAI and standard OpenAI APIs.
 * Manages a singleton client instance for AI-powered analysis.
 */

import OpenAI, { AzureOpenAI } from 'openai'

/** Singleton OpenAI client instance (either Azure or standard) */
let openaiClient: OpenAI | AzureOpenAI | null = null

/** Whether we're using Azure OpenAI or standard OpenAI */
let isAzure = false

/**
 * Get or initialize the OpenAI client.
 * Automatically detects whether to use Azure OpenAI or standard OpenAI
 * based on which environment variables are configured.
 * 
 * Azure OpenAI (checked first):
 * - AZURE_OPENAI_ENDPOINT: The Azure OpenAI resource endpoint URL
 * - AZURE_OPENAI_API_KEY: API key for authentication
 * - AZURE_OPENAI_DEPLOYMENT: Name of the deployed model
 * - OPENAI_API_VERSION: API version (default: '2024-12-01-preview')
 *
 * Standard OpenAI (fallback):
 * - OPENAI_API_KEY: API key for authentication
 * - OPENAI_MODEL: Model name (default: 'gpt-5.1-chat')
 * - OPENAI_BASE_URL: Optional custom base URL for OpenAI-compatible APIs
 *
 * @returns Configured OpenAI client or null if not configured
 */
export function getOpenAIClient(): OpenAI | AzureOpenAI | null {
  if (openaiClient) return openaiClient

  // Check for Azure OpenAI configuration first
  const azureEndpoint = process.env.AZURE_OPENAI_ENDPOINT
  const azureApiKey = process.env.AZURE_OPENAI_API_KEY
  const azureDeployment = process.env.AZURE_OPENAI_DEPLOYMENT

  if (azureEndpoint && azureApiKey && azureDeployment) {
    console.log('Using Azure OpenAI')
    isAzure = true
    openaiClient = new AzureOpenAI({
      endpoint: azureEndpoint,
      apiKey: azureApiKey,
      apiVersion: process.env.OPENAI_API_VERSION || '2024-12-01-preview',
      deployment: azureDeployment,
    })
    return openaiClient
  }

  // Fall back to standard OpenAI
  const openaiApiKey = process.env.OPENAI_API_KEY

  if (openaiApiKey) {
    console.log('Using standard OpenAI')
    isAzure = false
    openaiClient = new OpenAI({
      apiKey: openaiApiKey,
      baseURL: process.env.OPENAI_BASE_URL, // Optional: for OpenAI-compatible APIs
    })
    return openaiClient
  }

  console.warn(
    'OpenAI not configured. Set either:\n' +
    '  Azure: AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT\n' +
    '  OpenAI: OPENAI_API_KEY (and optionally OPENAI_MODEL, OPENAI_BASE_URL)'
  )
  return null
}

/**
 * Get the model/deployment name to use for API calls.
 * For Azure, returns the deployment name.
 * For standard OpenAI, returns the model name.
 *
 * @returns The model/deployment name or empty string if not configured
 */
export function getDeploymentName(): string {
  if (isAzure) {
    return process.env.AZURE_OPENAI_DEPLOYMENT || ''
  }
  return process.env.OPENAI_MODEL || 'gpt-5.1-chat'
}

/**
 * Check if OpenAI is properly configured.
 * Returns an error message if not configured, or null if configured.
 *
 * @returns Error message string if not configured, null if configured
 */
export function validateOpenAIConfig(): string | null {
  const azureEndpoint = process.env.AZURE_OPENAI_ENDPOINT
  const azureApiKey = process.env.AZURE_OPENAI_API_KEY
  const azureDeployment = process.env.AZURE_OPENAI_DEPLOYMENT
  const openaiApiKey = process.env.OPENAI_API_KEY

  // Check if Azure OpenAI is configured
  if (azureEndpoint && azureApiKey && azureDeployment) {
    return null
  }

  // Check if standard OpenAI is configured
  if (openaiApiKey) {
    return null
  }

  return (
    'OpenAI is not configured. Please set one of the following:\n' +
    '  Azure OpenAI: AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT\n' +
    '  Standard OpenAI: OPENAI_API_KEY (and optionally OPENAI_MODEL, OPENAI_BASE_URL)'
  )
}
