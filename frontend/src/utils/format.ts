import dayjs from 'dayjs'

export const formatDate = (date: string | number | Date, formatStr = 'YYYY-MM-DD HH:mm:ss') => {
  if (!date) return '-'
  return dayjs(date).format(formatStr)
}
