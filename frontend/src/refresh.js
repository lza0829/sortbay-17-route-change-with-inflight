import { useEffect, useState } from 'react'

// 全局数据版本号：任一会改变“路由/在途/口门/封袋/回流/总览”的写操作
// bump 之后，所有订阅页面重新拉取，保证同刷。
const EVENT = 'sortbay:refresh'

export function bump() {
  window.dispatchEvent(new Event(EVENT))
}

export function useRefreshKey() {
  const [key, setKey] = useState(0)
  useEffect(() => {
    const h = () => setKey((k) => k + 1)
    window.addEventListener(EVENT, h)
    return () => window.removeEventListener(EVENT, h)
  }, [])
  return key
}
