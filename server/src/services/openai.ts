/**
 * @fileoverview Azure OpenAI client configuration and initialization.
 * Manages a singleton client instance for AI-powered analysis.
 */

import { AzureOpenAI } from 'openai'

/** Singleton Azure OpenAI client instance */
let openaiClient: AzureOpenAI | null = null

/**
 * Get or initialize the Azure OpenAI client.
 * Returns null if required environment variables are not configured.
 *
 * Required environment variables:
 * - AZURE_OPENAI_ENDPOINT: The Azure OpenAI resource endpoint URL
 * - AZURE_OPENAI_API_KEY: API key for authentication
 * - AZURE_OPENAI_DEPLOYMENT: Name of the deployed model
 *
 * Optional:
 * - OPENAI_API_VERSION: API version (default: '2024-12-01-preview')
 *
 * @returns Configured AzureOpenAI client or null if not configured
 */
export function getOpenAIClient(): AzureOpenAI | null {
  if (openaiClient) return openaiClient

  const endpoint = process.env.AZURE_OPENAI_ENDPOINT
  const apiKey = process.env.AZURE_OPENAI_API_KEY
  const deployment = process.env.AZURE_OPENAI_DEPLOYMENT

  if (!endpoint || !apiKey || !deployment) {
    console.warn(
      'Azure OpenAI not configured. Set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, and AZURE_OPENAI_DEPLOYMENT in .env'
    )
    return null
  }

  openaiClient = new AzureOpenAI({
    endpoint,
    apiKey,
    apiVersion: process.env.OPENAI_API_VERSION || '2024-12-01-preview',
    deployment,
  })

  return openaiClient
}

/**
 * Get the Azure OpenAI deployment name from environment.
 *
 * @returns The deployment name or empty string if not configured
 */
export function getDeploymentName(): string {
  return process.env.AZURE_OPENAI_DEPLOYMENT || ''
}
