import client from './client'

export type TechPlatformModuleStatus = 'idle' | 'queued' | 'running' | 'success' | 'failed'

export interface TechPlatformDeploymentModule {
  id: string
  project_id: string
  site_id: string
  site_name: string
  dockerfile_path: string
  build_context: string
  app_name: string
  namespace: string
  harbor_project: string
  repository_name: string
  app_type: string
  container_port: number
  service_port: number
  config_map_template: string
  deployment_template: string
  service_template: string
  platform_app_id: string
  is_available: boolean
  last_task_id: string
  last_image: string
  last_commit_sha: string
  status: TechPlatformModuleStatus
  last_error: string
  last_deployed_at: string | null
  created_at: string | null
  updated_at: string | null
}

export type TechPlatformModuleInput = Pick<
  TechPlatformDeploymentModule,
  | 'site_id'
  | 'dockerfile_path'
  | 'build_context'
  | 'app_name'
  | 'namespace'
  | 'harbor_project'
  | 'repository_name'
  | 'app_type'
  | 'container_port'
  | 'service_port'
  | 'config_map_template'
  | 'deployment_template'
  | 'service_template'
>

export interface RenderedYamlResource {
  kind: 'ConfigMap' | 'Deployment' | 'Service'
  yaml: string
}

export const techPlatformAPI = {
  list(projectId: string) {
    return client.get<any, { ok: boolean; modules: TechPlatformDeploymentModule[] }>(
      `/projects/${projectId}/tech-platform/modules`,
    )
  },

  scan(projectId: string) {
    return client.post<any, { ok: boolean; modules: TechPlatformDeploymentModule[] }>(
      `/projects/${projectId}/tech-platform/modules/scan`,
    )
  },

  create(projectId: string, data: TechPlatformModuleInput) {
    return client.post<any, { ok: boolean; module: TechPlatformDeploymentModule }>(
      `/projects/${projectId}/tech-platform/modules`,
      data,
    )
  },

  update(projectId: string, moduleId: string, data: Partial<TechPlatformModuleInput>) {
    return client.patch<any, { ok: boolean; module: TechPlatformDeploymentModule }>(
      `/projects/${projectId}/tech-platform/modules/${moduleId}`,
      data,
    )
  },

  remove(projectId: string, moduleId: string) {
    return client.delete(`/projects/${projectId}/tech-platform/modules/${moduleId}`)
  },

  preview(projectId: string, moduleId: string, image = '') {
    return client.post<any, { ok: boolean; image: string; resources: RenderedYamlResource[] }>(
      `/projects/${projectId}/tech-platform/modules/${moduleId}/preview`,
      { image: image || null },
    )
  },

  validate(projectId: string, moduleId: string, image = '') {
    return client.post<any, { ok: boolean; valid: boolean; resources: RenderedYamlResource[] }>(
      `/projects/${projectId}/tech-platform/modules/${moduleId}/validate`,
      { image: image || null },
    )
  },

  deploy(projectId: string, moduleId: string) {
    return client.post<any, { ok: boolean; task_id: string }>(
      `/projects/${projectId}/tech-platform/modules/${moduleId}/deploy`,
    )
  },
}
