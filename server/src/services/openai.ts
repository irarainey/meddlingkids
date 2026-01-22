// Azure OpenAI client configuration

import { AzureOpenAI } from 'openai'

let openaiClient: AzureOpenAI | null = null

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

export function getDeploymentName(): string {
  return process.env.AZURE_OPENAI_DEPLOYMENT || ''
}
