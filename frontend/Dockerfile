# 阶段一：使用 Node.js 构建打包环境
FROM node:20-alpine AS build-stage

WORKDIR /app
# 优先复制依赖包管理文件，有效利用 Docker 构建缓存
COPY package*.json ./
RUN npm install

# 复制全部前端源码并编译
COPY . .
RUN npm run build

# 阶段二：使用 Nginx 提供生产级的 HTTP 静态服务
FROM nginx:alpine

# 将第一阶段的构建产物 dist 下发给 Nginx
COPY --from=build-stage /app/dist /usr/share/nginx/html

# 用定制的 Nginx 配置覆盖默认配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Nginx 监听 80 端口
EXPOSE 80

# 保持 Nginx 始终在前台执行作为 Docker 的 PID 1 进程
CMD ["nginx", "-g", "daemon off;"]
