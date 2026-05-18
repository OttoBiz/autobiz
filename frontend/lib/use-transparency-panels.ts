import { useCallback, useEffect, useRef, useState } from "react"

const FETCH_INIT: RequestInit = { cache: "no-store" }

export interface CatalogProductRow {
  id: string
  name?: string | null
  price: number
  stock_quantity: number
  currency?: string | null
}

export interface DiscussedProductRow {
  id?: string | null
  name?: string | null
  price: number
  stock_quantity: number
  currency?: string | null
  cache_key?: string
}

export interface SessionProcessRow {
  process_id: string
  task_type?: string
  product_name?: string
  order_id?: string
  order_number?: string
  status?: string
  quantity?: number | string | null
  tracking_number?: string
  logistic_id?: string | null
  customer_address?: string
  completed?: boolean
}

export interface InventoryActivityEvent {
  at?: string
  kind?: string
  product_id?: string
  name?: string | null
  stock_quantity?: number
  price?: number
  currency?: string | null
}

export interface SessionOrderRow {
  id: string
  order_number?: string | null
  status?: string | null
  total_amount?: number
  product_name?: string | null
  tracking_number?: string | null
  delivery_address?: string | null
  delivery_city?: string | null
  delivery_state?: string | null
  logistic_id?: string | null
  metadata?: Record<string, unknown> | null
  product_attributes?: Record<string, unknown> | null
  created_at?: string | null
  updated_at?: string | null
}

function bust(path: string): string {
  const sep = path.includes("?") ? "&" : "?"
  return `${path}${sep}_=${Date.now()}`
}

function isAbortError(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError"
}

async function readJson<T>(res: Response): Promise<T | null> {
  if (!res.ok) return null
  try {
    return (await res.json()) as T
  } catch {
    return null
  }
}

const EMPTY_CATALOG: CatalogProductRow[] = []
const EMPTY_DISCUSSED: DiscussedProductRow[] = []
const EMPTY_PROCESSES: SessionProcessRow[] = []
const EMPTY_ACTIVITY: InventoryActivityEvent[] = []
const EMPTY_ORDERS: SessionOrderRow[] = []

function useRefreshCounter() {
  const countRef = useRef(0)
  const [refreshing, setRefreshing] = useState(false)

  const begin = useCallback(() => {
    countRef.current += 1
    setRefreshing(true)
  }, [])

  const end = useCallback(() => {
    countRef.current = Math.max(0, countRef.current - 1)
    if (countRef.current === 0) setRefreshing(false)
  }, [])

  return { refreshing, begin, end }
}

export function useTransparencyPanels(
  apiBase: string,
  businessId: string | undefined,
  userId: string | undefined,
  pollMs: number,
) {
  const [topProducts, setTopProducts] = useState<CatalogProductRow[]>(EMPTY_CATALOG)
  const [agentProducts, setAgentProducts] = useState<DiscussedProductRow[]>(EMPTY_DISCUSSED)
  const [agentProcesses, setAgentProcesses] = useState<SessionProcessRow[]>(EMPTY_PROCESSES)
  const [inventoryActivity, setInventoryActivity] = useState<InventoryActivityEvent[]>(EMPTY_ACTIVITY)
  const [activeSessionOrders, setActiveSessionOrders] = useState<SessionOrderRow[]>(EMPTY_ORDERS)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)
  const [fetchError, setFetchError] = useState<string | null>(null)

  const { refreshing, begin, end } = useRefreshCounter()
  const allAbortRef = useRef<AbortController | null>(null)
  const sessionAbortRef = useRef<AbortController | null>(null)
  const allInFlightRef = useRef(false)

  const applySessionPayload = useCallback(
    (data: {
      products_discussed?: DiscussedProductRow[]
      processes?: SessionProcessRow[]
    } | null) => {
      setAgentProducts(
        Array.isArray(data?.products_discussed) ? data.products_discussed : EMPTY_DISCUSSED,
      )
      setAgentProcesses(Array.isArray(data?.processes) ? data.processes : EMPTY_PROCESSES)
    },
    [],
  )

  const fetchSession = useCallback(
    async (signal: AbortSignal) => {
      if (!businessId || !userId) return null
      const res = await fetch(
        bust(
          `${apiBase}/api/v1/session/agent-context?user_id=${encodeURIComponent(userId)}&vendor_id=${encodeURIComponent(businessId)}`,
        ),
        { ...FETCH_INIT, signal },
      )
      return readJson<{
        products_discussed?: DiscussedProductRow[]
        processes?: SessionProcessRow[]
      }>(res)
    },
    [apiBase, businessId, userId],
  )

  const loadSession = useCallback(async () => {
    if (!businessId || !userId) {
      setFetchError("Select user and business to refresh session panels")
      return
    }

    sessionAbortRef.current?.abort()
    const ac = new AbortController()
    sessionAbortRef.current = ac
    begin()
    setFetchError(null)
    try {
      const data = await fetchSession(ac.signal)
      if (ac.signal.aborted) return
      if (!data) {
        setFetchError("Session refresh failed")
        return
      }
      applySessionPayload(data)
      setUpdatedAt(new Date())
    } catch (err) {
      if (!isAbortError(err) && !ac.signal.aborted) {
        setFetchError("Session refresh failed")
      }
    } finally {
      end()
    }
  }, [applySessionPayload, begin, businessId, end, fetchSession, userId])

  const loadAll = useCallback(
    async (opts?: { force?: boolean }) => {
      if (allInFlightRef.current && !opts?.force) return

      allAbortRef.current?.abort()
      const ac = new AbortController()
      allAbortRef.current = ac
      allInFlightRef.current = true
      begin()
      setFetchError(null)

      if (!businessId) {
        setTopProducts(EMPTY_CATALOG)
        setAgentProducts(EMPTY_DISCUSSED)
        setAgentProcesses(EMPTY_PROCESSES)
        setInventoryActivity(EMPTY_ACTIVITY)
        setActiveSessionOrders(EMPTY_ORDERS)
        allInFlightRef.current = false
        end()
        return
      }

      try {
        const catalogUrl = bust(
          `${apiBase}/api/v1/inventory/top-products/${businessId}?limit=15`,
        )
        const activityUrl = bust(`${apiBase}/api/v1/inventory/activity/${businessId}?limit=40`)
        const sessionUrl =
          userId &&
          bust(
            `${apiBase}/api/v1/session/agent-context?user_id=${encodeURIComponent(userId)}&vendor_id=${encodeURIComponent(businessId)}`,
          )
        const ordersUrl =
          userId &&
          bust(
            `${apiBase}/api/v1/session/active-orders?user_id=${encodeURIComponent(userId)}&vendor_id=${encodeURIComponent(businessId)}&limit=25`,
          )

        const [catalogRes, activityRes, sessionRes, ordersRes] = await Promise.all([
          fetch(catalogUrl, { ...FETCH_INIT, signal: ac.signal }),
          fetch(activityUrl, { ...FETCH_INIT, signal: ac.signal }),
          sessionUrl ? fetch(sessionUrl, { ...FETCH_INIT, signal: ac.signal }) : Promise.resolve(null),
          ordersUrl ? fetch(ordersUrl, { ...FETCH_INIT, signal: ac.signal }) : Promise.resolve(null),
        ])

        if (ac.signal.aborted) return

        let hadError = false

        const catalog = await readJson<{ products?: CatalogProductRow[] }>(catalogRes)
        if (catalog) {
          setTopProducts(Array.isArray(catalog.products) ? catalog.products : EMPTY_CATALOG)
        } else hadError = true

        const activity = await readJson<{ events?: InventoryActivityEvent[] }>(activityRes)
        if (activity) {
          setInventoryActivity(
            Array.isArray(activity.events) ? activity.events : EMPTY_ACTIVITY,
          )
        } else hadError = true

        if (sessionRes) {
          const session = await readJson<{
            products_discussed?: DiscussedProductRow[]
            processes?: SessionProcessRow[]
          }>(sessionRes)
          if (session) applySessionPayload(session)
          else hadError = true
        } else {
          setAgentProducts(EMPTY_DISCUSSED)
          setAgentProcesses(EMPTY_PROCESSES)
        }

        if (ordersRes) {
          const orders = await readJson<{ orders?: SessionOrderRow[] }>(ordersRes)
          if (orders) {
            setActiveSessionOrders(
              Array.isArray(orders.orders) ? orders.orders : EMPTY_ORDERS,
            )
          } else hadError = true
        } else {
          setActiveSessionOrders(EMPTY_ORDERS)
        }

        setUpdatedAt(new Date())
        if (hadError) setFetchError("Some panels failed to refresh")
      } catch (err) {
        if (!isAbortError(err) && !ac.signal.aborted) {
          setFetchError("Refresh failed")
        }
      } finally {
        allInFlightRef.current = false
        end()
      }
    },
    [apiBase, applySessionPayload, begin, businessId, end, userId],
  )

  const refreshAll = useCallback(() => loadAll({ force: true }), [loadAll])

  useEffect(() => {
    void loadAll({ force: true })
    const interval = setInterval(() => void loadAll(), pollMs)
    return () => {
      clearInterval(interval)
      allAbortRef.current?.abort()
      sessionAbortRef.current?.abort()
    }
  }, [loadAll, pollMs])

  return {
    topProducts,
    agentProducts,
    agentProcesses,
    inventoryActivity,
    activeSessionOrders,
    refreshing,
    updatedAt,
    fetchError,
    loadAll: refreshAll,
    loadSession,
  }
}
