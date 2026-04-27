import { defineStore } from 'pinia'
import { projectsAPI } from '@/api/projects'
import type { Project, Site } from '@/types/models'

interface ProjectState {
  projects: Project[]
  currentProject: Project | null
  loading: boolean
}

export const useProjectStore = defineStore('project', {
  state: (): ProjectState => ({
    projects: [],
    currentProject: null,
    loading: false,
  }),

  actions: {
    async fetchProjects() {
      this.loading = true
      try {
        const response = await projectsAPI.list()
        this.projects = response.projects
      } finally {
        this.loading = false
      }
    },

    async fetchProject(projectId: string) {
      this.loading = true
      try {
        const response = await projectsAPI.get(projectId)
        this.currentProject = response.project
        return response.project
      } finally {
        this.loading = false
      }
    },

    async createProject(data: { name: string; description?: string }) {
      const response = await projectsAPI.create(data)
      this.projects.unshift(response.project)
      return response.project
    },

    async deleteProject(projectId: string) {
      await projectsAPI.delete(projectId)
      this.projects = this.projects.filter((p) => p.id !== projectId)
    },

    async addRepo(projectId: string, data: { name: string; git_url?: string; git_branch?: string; git_username?: string; git_password?: string }) {
      const response = await projectsAPI.addRepo(projectId, data)
      if (this.currentProject?.id === projectId) {
        await this.fetchProject(projectId)
      }
      return response.repo
    },

    async deleteRepo(projectId: string, repoId: string) {
      await projectsAPI.deleteRepo(projectId, repoId)
      if (this.currentProject?.id === projectId) {
        await this.fetchProject(projectId)
      }
    },
  },
})
