import { defineStore } from 'pinia'
import { sitesAPI } from '@/api/sites'
import type { Site } from '@/types/models'

interface SiteState {
  sites: Site[]
  currentSite: Site | null
  loading: boolean
}

export const useSiteStore = defineStore('site', {
  state: (): SiteState => ({
    sites: [],
    currentSite: null,
    loading: false,
  }),

  getters: {
    runningSites: (state) => state.sites.filter((s) => s.status === 'running'),
  },

  actions: {
    // 获取站点列表
    async fetchSites() {
      this.loading = true
      try {
        const response = await sitesAPI.list()
        this.sites = response.sites
      } finally {
        this.loading = false
      }
    },

    // 获取单个站点
    async fetchSite(siteId: string) {
      this.loading = true
      try {
        const response = await sitesAPI.get(siteId)
        this.currentSite = response.site
        return response.site
      } finally {
        this.loading = false
      }
    },

    // 创建站点
    async createSite(data: {
      name: string
      template_id?: string
      git_url?: string
      git_branch?: string
      git_username?: string
      git_password?: string
      start_command?: string
    }) {
      const response = await sitesAPI.create(data)
      this.sites.unshift(response.site)
      return response.site
    },

    // 启动站点
    async startSite(siteId: string) {
      await sitesAPI.start(siteId)
      const site = this.sites.find((s) => s.site_id === siteId)
      if (site) {
        site.status = 'running'
      }
    },

    // 停止站点
    async stopSite(siteId: string) {
      await sitesAPI.stop(siteId)
      const site = this.sites.find((s) => s.site_id === siteId)
      if (site) {
        site.status = 'stopped'
      }
    },

    // 删除站点
    async deleteSite(siteId: string) {
      await sitesAPI.delete(siteId)
      this.sites = this.sites.filter((s) => s.site_id !== siteId)
    },
  },
})
