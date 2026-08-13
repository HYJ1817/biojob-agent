import assert from 'node:assert/strict'

import { test } from 'vitest'

import { resolveBioJobHome } from './biojob-home'

test('packaged Windows BioJob ignores an existing Hermes home', () => {
  const actual = resolveBioJobHome({
    platform: 'win32',
    env: {
      LOCALAPPDATA: 'C:\\Users\\test\\AppData\\Local',
      HERMES_HOME: 'D:\\OldHermes'
    },
    packaged: true,
    userDataOverride: null,
    homeDir: 'C:\\Users\\test'
  })

  assert.equal(actual, 'C:\\Users\\test\\AppData\\Local\\BioJob Agent')
})

test('desktop sandbox override has highest precedence', () => {
  const actual = resolveBioJobHome({
    platform: 'win32',
    env: { HERMES_HOME: 'D:\\OldHermes' },
    packaged: true,
    userDataOverride: 'D:\\sandbox',
    homeDir: 'C:\\Users\\test'
  })

  assert.equal(actual, 'D:\\sandbox\\biojob-home')
})

test('development builds may explicitly reuse HERMES_HOME', () => {
  const actual = resolveBioJobHome({
    platform: 'linux',
    env: { HERMES_HOME: '/tmp/hermes-dev' },
    packaged: false,
    userDataOverride: null,
    homeDir: '/home/test'
  })

  assert.equal(actual, '/tmp/hermes-dev')
})

test('packaged macOS and Linux builds use BioJob-specific homes', () => {
  assert.equal(
    resolveBioJobHome({
      platform: 'darwin',
      env: {},
      packaged: true,
      userDataOverride: null,
      homeDir: '/Users/test'
    }),
    '/Users/test/Library/Application Support/BioJob Agent/runtime'
  )
  assert.equal(
    resolveBioJobHome({
      platform: 'linux',
      env: { XDG_DATA_HOME: '/var/data' },
      packaged: true,
      userDataOverride: null,
      homeDir: '/home/test'
    }),
    '/var/data/biojob-agent'
  )
})

