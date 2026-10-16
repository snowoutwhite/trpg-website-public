/**
 * 时间显示与表单输入的互转。
 *
 * 后端 `USE_TZ=True` + `TIME_ZONE='Asia/Shanghai'`，DRF 回的是带时区偏移的 ISO 串；
 * 浏览器 `datetime-local` 输入框收发的是**无时区的本地时间串**（YYYY-MM-DDTHH:mm）。
 * 这两种形状必须在同一处转换，否则各页面各写一遍就会出现「差 8 小时」这类经典坑。
 */

/** 「2026-09-25 19:00」——列表与详情里的开团时间统一这个写法（精确到分钟）。 */
export function formatDateTime(value?: string | null): string {
  if (!value) return ''
  const time = new Date(value)
  if (Number.isNaN(time.getTime())) return ''
  return time.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

/** 只要日期的地方（发布时间、结团时间）。 */
export function formatDate(value?: string | null): string {
  if (!value) return ''
  const time = new Date(value)
  if (Number.isNaN(time.getTime())) return ''
  return time.toLocaleDateString('zh-CN')
}

/** ISO → `datetime-local` 输入框的值（本地时区，分钟精度）。 */
export function toLocalInput(value?: string | null): string {
  if (!value) return ''
  const time = new Date(value)
  if (Number.isNaN(time.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return (
    time.getFullYear() +
    '-' +
    pad(time.getMonth() + 1) +
    '-' +
    pad(time.getDate()) +
    'T' +
    pad(time.getHours()) +
    ':' +
    pad(time.getMinutes())
  )
}

/** `datetime-local` 的值 → ISO 串。空串返回 null（= 字段留空）。 */
export function fromLocalInput(value: string): string | null {
  if (!value) return null
  // 规范规定无偏移的 datetime-local 串按**本地时区**解析，正是输入框的语义。
  const time = new Date(value)
  if (Number.isNaN(time.getTime())) return null
  return time.toISOString()
}

/** 距离某个时刻还剩多久的粗粒度说法，用在交卡截止 / 评价窗口这类提醒上。 */
export function timeLeft(value?: string | null): string {
  if (!value) return ''
  const target = new Date(value).getTime()
  if (Number.isNaN(target)) return ''
  const diff = target - Date.now()
  if (diff <= 0) return '已过期'
  const hours = Math.floor(diff / 3_600_000)
  if (hours < 1) return '不足 1 小时'
  if (hours < 48) return '还剩约 ' + hours + ' 小时'
  return '还剩约 ' + Math.floor(hours / 24) + ' 天'
}
