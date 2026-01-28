/**
 * @fileoverview Device configuration profiles for browser emulation.
 * Defines user agents, viewports, and capabilities for different device types.
 */

// ============================================================================
// Types
// ============================================================================

/** Device type identifiers */
export type DeviceType = 'iphone' | 'ipad' | 'android-phone' | 'android-tablet' | 'windows-chrome' | 'macos-safari'

/** Device configuration for browser emulation */
export interface DeviceConfig {
  userAgent: string
  viewport: { width: number; height: number }
  deviceScaleFactor: number
  isMobile: boolean
  hasTouch: boolean
}

// ============================================================================
// Device Configurations
// ============================================================================

/** Device configurations for different browser/device combinations */
export const DEVICE_CONFIGS: Record<DeviceType, DeviceConfig> = {
  'iphone': {
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1',
    viewport: { width: 430, height: 932 },
    deviceScaleFactor: 3,
    isMobile: true,
    hasTouch: true,
  },
  'ipad': {
    userAgent: 'Mozilla/5.0 (iPad; CPU OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1',
    viewport: { width: 1024, height: 1366 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
  },
  'android-phone': {
    userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.90 Mobile Safari/537.36',
    viewport: { width: 412, height: 915 },
    deviceScaleFactor: 2.625,
    isMobile: true,
    hasTouch: true,
  },
  'android-tablet': {
    userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel Tablet) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.90 Safari/537.36',
    viewport: { width: 1280, height: 800 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
  },
  'windows-chrome': {
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
    isMobile: false,
    hasTouch: false,
  },
  'macos-safari': {
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15',
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
    isMobile: false,
    hasTouch: false,
  },
}

/**
 * Get device configuration by type.
 * 
 * @param deviceType - The device type identifier
 * @returns Device configuration for browser emulation
 */
export function getDeviceConfig(deviceType: DeviceType): DeviceConfig {
  return DEVICE_CONFIGS[deviceType]
}

/**
 * Check if a device type is valid.
 * 
 * @param deviceType - The device type to validate
 * @returns True if the device type is valid
 */
export function isValidDeviceType(deviceType: string): deviceType is DeviceType {
  return deviceType in DEVICE_CONFIGS
}
