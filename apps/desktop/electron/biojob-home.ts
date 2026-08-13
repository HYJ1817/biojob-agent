import path from 'node:path'

export interface BioJobHomeOptions {
  platform: NodeJS.Platform
  env: NodeJS.ProcessEnv
  packaged: boolean
  userDataOverride?: string | null
  homeDir: string
}

export type LegacyHermesHomeOptions = Pick<BioJobHomeOptions, 'platform' | 'env' | 'homeDir'>

function pathApi(platform: NodeJS.Platform) {
  return platform === 'win32' ? path.win32 : path.posix
}

export function resolveBioJobHome(options: BioJobHomeOptions): string {
  const paths = pathApi(options.platform)

  if (options.userDataOverride) {
    return paths.join(paths.resolve(options.userDataOverride), 'biojob-home')
  }

  if (!options.packaged && options.env.HERMES_HOME) {
    return paths.resolve(options.env.HERMES_HOME)
  }

  if (options.platform === 'win32' && options.env.LOCALAPPDATA) {
    return paths.join(options.env.LOCALAPPDATA, 'BioJob Agent')
  }

  if (options.platform === 'darwin') {
    return paths.join(options.homeDir, 'Library', 'Application Support', 'BioJob Agent', 'runtime')
  }

  return paths.join(options.env.XDG_DATA_HOME || paths.join(options.homeDir, '.local', 'share'), 'biojob-agent')
}

export function resolveLegacyHermesHome(options: LegacyHermesHomeOptions): string | null {
  if (options.platform !== 'win32' || !options.env.LOCALAPPDATA) {
    return null
  }

  return path.win32.join(options.env.LOCALAPPDATA, 'hermes')
}
