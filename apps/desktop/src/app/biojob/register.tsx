import { registry } from '@/contrib/registry'

import { type RouteContribution, ROUTES_AREA, SIDEBAR_NAV_AREA, type SidebarNavContribution } from '../routes'

import { BioJobWorkbench } from './index'

registry.registerMany([
  {
    area: ROUTES_AREA,
    id: 'biojob',
    order: 10,
    title: 'BioJob',
    data: { path: '/biojob' } satisfies RouteContribution,
    render: () => <BioJobWorkbench />
  },
  {
    area: SIDEBAR_NAV_AREA,
    id: 'biojob',
    order: 5,
    data: { codicon: 'briefcase', label: 'BioJob', path: '/biojob' } satisfies SidebarNavContribution
  }
])
