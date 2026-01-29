/**
 * @fileoverview Logging utility with timestamps and timing support.
 * Provides structured, colorful console output for tracking analysis stages.
 * Optionally writes logs to a timestamped file when WRITE_LOG_TO_FILE is set.
 */

import * as fs from 'fs'
import * as path from 'path'

// ============================================================================
// Types
// ============================================================================

/** Log level for categorizing messages */
type LogLevel = 'info' | 'success' | 'warn' | 'error' | 'debug' | 'timing'

/** Timer storage for tracking operation durations */
const timers: Map<string, number> = new Map()

// ============================================================================
// File Logging Setup
// ============================================================================

/** Whether to write logs to file */
const writeToFile = process.env.WRITE_LOG_TO_FILE === 'true'

/** Log file path (created once at startup) */
let logFilePath: string | null = null

/** Log file write stream */
let logFileStream: fs.WriteStream | null = null

/**
 * Initialize file logging if enabled.
 */
function initFileLogging(): void {
  if (!writeToFile || logFileStream) return
  
  // Create logs directory if it doesn't exist
  const logsDir = path.resolve(process.cwd(), 'logs')
  if (!fs.existsSync(logsDir)) {
    fs.mkdirSync(logsDir, { recursive: true })
  }
  
  // Create timestamped log file
  const now = new Date()
  const timestamp = now.toISOString()
    .replace(/[:.]/g, '-')
    .replace('T', '_')
    .slice(0, 19)
  logFilePath = path.join(logsDir, `meddlingkids_${timestamp}.log`)
  
  logFileStream = fs.createWriteStream(logFilePath, { flags: 'a' })
  
  // Write header
  const header = `
================================================================================
  Meddling Kids Log - Started ${now.toISOString()}
================================================================================
`
  logFileStream.write(header)
  
  // Log to console that file logging is enabled
  console.log(`\x1b[36mℹ [Logger] Writing logs to: ${logFilePath}\x1b[0m`)
}

/**
 * Write a line to the log file (without ANSI colors).
 */
function writeToLogFile(line: string): void {
  if (!logFileStream) return
  
  // Strip ANSI escape codes for file output
  // eslint-disable-next-line no-control-regex
  const cleanLine = line.replace(/\x1b\[[0-9;]*m/g, '')
  logFileStream.write(cleanLine + '\n')
}

// Initialize file logging on module load
initFileLogging()

// ============================================================================
// ANSI Colors
// ============================================================================

const colors = {
  reset: '\x1b[0m',
  bright: '\x1b[1m',
  dim: '\x1b[2m',
  cyan: '\x1b[36m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  red: '\x1b[31m',
  magenta: '\x1b[35m',
  blue: '\x1b[34m',
  gray: '\x1b[90m',
}

// ============================================================================
// Formatting Helpers
// ============================================================================

/**
 * Get current timestamp in HH:MM:SS.mmm format.
 */
function getTimestamp(): string {
  const now = new Date()
  const hours = now.getHours().toString().padStart(2, '0')
  const minutes = now.getMinutes().toString().padStart(2, '0')
  const seconds = now.getSeconds().toString().padStart(2, '0')
  const ms = now.getMilliseconds().toString().padStart(3, '0')
  return `${hours}:${minutes}:${seconds}.${ms}`
}

/**
 * Format duration in milliseconds to human-readable string.
 */
function formatDuration(ms: number): string {
  if (ms < 1000) {
    return `${ms}ms`
  }
  if (ms < 60000) {
    return `${(ms / 1000).toFixed(2)}s`
  }
  const minutes = Math.floor(ms / 60000)
  const seconds = ((ms % 60000) / 1000).toFixed(1)
  return `${minutes}m ${seconds}s`
}

/**
 * Get color code for log level.
 */
function getLevelColor(level: LogLevel): string {
  switch (level) {
    case 'info': return colors.cyan
    case 'success': return colors.green
    case 'warn': return colors.yellow
    case 'error': return colors.red
    case 'debug': return colors.gray
    case 'timing': return colors.magenta
  }
}

/**
 * Get level prefix symbol.
 */
function getLevelSymbol(level: LogLevel): string {
  switch (level) {
    case 'info': return 'ℹ'
    case 'success': return '✓'
    case 'warn': return '⚠'
    case 'error': return '✗'
    case 'debug': return '•'
    case 'timing': return '⏱'
  }
}

// ============================================================================
// Core Logger
// ============================================================================

/**
 * Logger class for structured console output.
 */
class Logger {
  private context: string

  constructor(context: string = 'Server') {
    this.context = context
  }

  /**
   * Create a child logger with a new context.
   */
  child(context: string): Logger {
    return new Logger(context)
  }

  /**
   * Internal log method.
   */
  private log(level: LogLevel, message: string, data?: Record<string, unknown>): void {
    const timestamp = getTimestamp()
    const color = getLevelColor(level)
    const symbol = getLevelSymbol(level)
    
    const prefix = `${colors.gray}[${timestamp}]${colors.reset} ${color}${symbol}${colors.reset} ${colors.bright}[${this.context}]${colors.reset}`
    
    let logLine: string
    if (data && Object.keys(data).length > 0) {
      const dataStr = Object.entries(data)
        .map(([k, v]) => `${colors.dim}${k}=${colors.reset}${formatValue(v)}`)
        .join(' ')
      logLine = `${prefix} ${message} ${dataStr}`
    } else {
      logLine = `${prefix} ${message}`
    }
    
    console.log(logLine)
    writeToLogFile(logLine)
  }

  /** Log info message */
  info(message: string, data?: Record<string, unknown>): void {
    this.log('info', message, data)
  }

  /** Log success message */
  success(message: string, data?: Record<string, unknown>): void {
    this.log('success', message, data)
  }

  /** Log warning message */
  warn(message: string, data?: Record<string, unknown>): void {
    this.log('warn', message, data)
  }

  /** Log error message */
  error(message: string, data?: Record<string, unknown>): void {
    this.log('error', message, data)
  }

  /** Log debug message */
  debug(message: string, data?: Record<string, unknown>): void {
    this.log('debug', message, data)
  }

  /**
   * Start a timer for an operation.
   * @param label - Unique label for the timer
   */
  startTimer(label: string): void {
    const key = `${this.context}:${label}`
    timers.set(key, Date.now())
    this.log('timing', `Starting: ${label}`)
  }

  /**
   * End a timer and log the duration.
   * @param label - The timer label (must match startTimer)
   * @param message - Optional completion message
   * @returns Duration in milliseconds
   */
  endTimer(label: string, message?: string): number {
    const key = `${this.context}:${label}`
    const start = timers.get(key)
    
    if (!start) {
      this.warn(`Timer "${label}" was not started`)
      return 0
    }
    
    const duration = Date.now() - start
    timers.delete(key)
    
    const durationStr = `${colors.magenta}${formatDuration(duration)}${colors.reset}`
    const displayMessage = message || `Completed: ${label}`
    this.log('timing', `${displayMessage} ${colors.dim}took${colors.reset} ${durationStr}`)
    
    return duration
  }

  /**
   * Log a section header for visual separation.
   */
  section(title: string): void {
    const line = '─'.repeat(60)
    const output = [
      '',
      `${colors.blue}${line}${colors.reset}`,
      `${colors.blue}${colors.bright}  ${title}${colors.reset}`,
      `${colors.blue}${line}${colors.reset}`,
      ''
    ]
    output.forEach(l => {
      console.log(l)
      writeToLogFile(l)
    })
  }

  /**
   * Log a subsection header.
   */
  subsection(title: string): void {
    const output = `\n${colors.cyan}  ▸ ${title}${colors.reset}`
    console.log(output)
    writeToLogFile(output)
  }
}

/**
 * Format a value for display.
 */
function formatValue(value: unknown): string {
  if (value === null || value === undefined) {
    return `${colors.dim}null${colors.reset}`
  }
  if (typeof value === 'number') {
    return `${colors.yellow}${value}${colors.reset}`
  }
  if (typeof value === 'boolean') {
    return value ? `${colors.green}true${colors.reset}` : `${colors.red}false${colors.reset}`
  }
  if (typeof value === 'string') {
    // Truncate long strings
    const display = value.length > 50 ? value.substring(0, 47) + '...' : value
    return `${colors.green}"${display}"${colors.reset}`
  }
  if (Array.isArray(value)) {
    return `${colors.cyan}[${value.length} items]${colors.reset}`
  }
  if (typeof value === 'object') {
    const keys = Object.keys(value).length
    return `${colors.cyan}{${keys} keys}${colors.reset}`
  }
  return String(value)
}

// ============================================================================
// Exports
// ============================================================================

/** Main logger instance */
export const logger = new Logger('Server')

/** Create a logger for a specific module */
export function createLogger(context: string): Logger {
  return new Logger(context)
}
