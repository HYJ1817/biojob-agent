import { describe, expect, it } from 'vitest'

import { registry } from '@/contrib/registry'

import { appViewForPath, contributedRoutes, routeSessionId, SIDEBAR_NAV_AREA } from '../routes'

describe('BioJob workspace registration', () => {
  it('reserves a dedicated full-page route and sidebar destination', async () => {
    await import('./register')

    const route = contributedRoutes().find(item => item.path === '/biojob')
    const nav = registry.getArea(SIDEBAR_NAV_AREA).find(item => item.id === 'biojob')

    expect(route?.title).toBe('BioJob')
    expect(typeof route?.render).toBe('function')
    expect(nav?.data).toEqual({ codicon: 'briefcase', label: 'BioJob', path: '/biojob' })
    expect(appViewForPath('/biojob')).toBe('extension')
    expect(routeSessionId('/biojob')).toBeNull()
  })
})
