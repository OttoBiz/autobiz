"use client"

import type React from "react"
import { useState, useRef, useEffect } from "react"
import {
  Send,
  Mic,
  MicOff,
  Paperclip,
  User,
  Building2,
  Truck,
  TrendingUp,
  Package,
  BarChart3,
  Key,
  X,
  ImageIcon,
  Volume2,
  FileText,
  ShoppingCart,
  Users,
} from "lucide-react"

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000"

interface ChatMessage {
  id: string
  content: string
  sender: "user" | "ai"
  timestamp: Date
  customer_id?: string
  product_name?: string
  order_id?: string
}

interface Persona {
  id: string
  name: string
}

const predefinedUsers: Persona[] = [
  { id: "00000000-0000-0000-0000-000000000001", name: "John Doe" },
  { id: "00000000-0000-0000-0000-000000000002", name: "Sarah Johnson" },
  { id: "00000000-0000-0000-0000-000000000003", name: "Michael Chen" },
  { id: "00000000-0000-0000-0000-000000000004", name: "Emily Rodriguez" },
  { id: "00000000-0000-0000-0000-000000000005", name: "David Wilson" },
  { id: "00000000-0000-0000-0000-000000000006", name: "Lisa Thompson" },
]

const predefinedBusinesses: Persona[] = [
  { id: "00000000-0000-0000-0001-000000000001", name: "Donrey Fashion" },
  { id: "00000000-0000-0000-0001-000000000002", name: "Junae Cosmetics" },
  { id: "00000000-0000-0000-0001-000000000003", name: "Manny Gadgets" },
  { id: "00000000-0000-0000-0001-000000000004", name: "Tesla Tech" },
  { id: "00000000-0000-0000-0001-000000000005", name: "Kemi Surprises" },
]

const predefinedLogistics: Persona[] = [
  { id: "00000000-0000-0000-0002-000000000001", name: "Fast Delivery Co" },
  { id: "00000000-0000-0000-0002-000000000002", name: "Express Logistics" },
  { id: "00000000-0000-0000-0002-000000000003", name: "Quick Ship" },
]

export default function Page() {
  // Customer chat state
  const [customerMessages, setCustomerMessages] = useState<ChatMessage[]>([
    {
      id: "welcome-customer",
      content: "Hello! Select a user and business to start chatting.",
      sender: "ai",
      timestamp: new Date(),
    },
  ])
  const [customerInput, setCustomerInput] = useState("")
  const [selectedUser, setSelectedUser] = useState<Persona | null>(null)
  const [isCustomerLoading, setIsCustomerLoading] = useState(false)

  // Business chat state
  const [businessMessages, setBusinessMessages] = useState<ChatMessage[]>([
    {
      id: "welcome-business",
      content: "Select a business to start chatting.",
      sender: "ai",
      timestamp: new Date(),
    },
  ])
  const [businessInput, setBusinessInput] = useState("")
  const [selectedBusiness, setSelectedBusiness] = useState<Persona | null>(null)
  const [isBusinessLoading, setIsBusinessLoading] = useState(false)

  // Logistics chat state
  const [logisticsMessages, setLogisticsMessages] = useState<ChatMessage[]>([
    {
      id: "welcome-logistics",
      content: "Select a logistics company to start chatting.",
      sender: "ai",
      timestamp: new Date(),
    },
  ])
  const [logisticsInput, setLogisticsInput] = useState("")
  const [selectedLogistics, setSelectedLogistics] = useState<Persona | null>(null)
  const [isLogisticsLoading, setIsLogisticsLoading] = useState(false)

  // Analytics state
  const [businessAnalytics, setBusinessAnalytics] = useState<any>(null)
  const [userAnalytics, setUserAnalytics] = useState<any>(null)
  const [inventoryData, setInventoryData] = useState<any>(null)
  const [supplyChainData, setSupplyChainData] = useState<any>(null)
  const [isLoadingAnalytics, setIsLoadingAnalytics] = useState(false)

  const [customerSessionId, setCustomerSessionId] = useState(() => crypto.randomUUID())
  const [businessSessionId, setBusinessSessionId] = useState(() => crypto.randomUUID())
  const [logisticsSessionId, setLogisticsSessionId] = useState(() => crypto.randomUUID())

  const [apiKey, setApiKey] = useState("")

  const customerMessagesEndRef = useRef<HTMLDivElement>(null)
  const businessMessagesEndRef = useRef<HTMLDivElement>(null)
  const logisticsMessagesEndRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = (ref: React.RefObject<HTMLDivElement>) => {
    ref.current?.scrollIntoView({ behavior: "smooth" })
  }

  useEffect(() => {
    scrollToBottom(customerMessagesEndRef)
  }, [customerMessages])

  useEffect(() => {
    scrollToBottom(businessMessagesEndRef)
  }, [businessMessages])

  useEffect(() => {
    scrollToBottom(logisticsMessagesEndRef)
  }, [logisticsMessages])

  useEffect(() => {
    if (!selectedBusiness && !selectedLogistics) return

    const interval = setInterval(async () => {
      if (selectedBusiness) {
        try {
          const res = await fetch(`${BACKEND_URL}/api/v1/business/inbox/${selectedBusiness.id}`)
          const data = await res.json()
          if (data.messages?.length > 0) {
            const incoming = data.messages.map((m: { message: string; sender: string; customer_id?: string; product_name?: string; order_id?: string }, i: number) => {
              const ctx = [m.customer_id, m.product_name, m.order_id].filter(Boolean).join(" · ")
              return {
                id: `inbox-${Date.now()}-${i}`,
                content: ctx ? `[Re: ${ctx}] [From ${m.sender}] ${m.message}` : `[From ${m.sender}] ${m.message}`,
                sender: "ai" as const,
                timestamp: new Date(),
                customer_id: m.customer_id,
                product_name: m.product_name,
                order_id: m.order_id,
              }
            })
            setBusinessMessages((prev) => [...prev, ...incoming])
          }
        } catch (_) {}
      }

      if (selectedLogistics) {
        try {
          const res = await fetch(`${BACKEND_URL}/api/v1/logistics/inbox/${selectedLogistics.id}`)
          const data = await res.json()
          if (data.messages?.length > 0) {
            const incoming = data.messages.map((m: { message: string; sender: string; customer_id?: string; product_name?: string; order_id?: string }, i: number) => {
              const ctx = [m.customer_id, m.product_name, m.order_id].filter(Boolean).join(" · ")
              return {
                id: `inbox-${Date.now()}-${i}`,
                content: ctx ? `[Re: ${ctx}] [From ${m.sender}] ${m.message}` : `[From ${m.sender}] ${m.message}`,
                sender: "ai" as const,
                timestamp: new Date(),
                customer_id: m.customer_id,
                product_name: m.product_name,
                order_id: m.order_id,
              }
            })
            setLogisticsMessages((prev) => [...prev, ...incoming])
          }
        } catch (_) {}
      }
    }, 3000)

    return () => clearInterval(interval)
  }, [selectedBusiness, selectedLogistics])

  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || [])
    setSelectedFiles((prev) => [...prev, ...files])
    if (event.target) {
      event.target.value = ""
    }
  }

  const removeFile = (index: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index))
  }

  // Customer chat handlers
  const handleCustomerSend = async () => {
    if ((!customerInput.trim() && selectedFiles.length === 0) || !selectedUser || !selectedBusiness) return

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      content: customerInput || "File(s) uploaded",
      sender: "user",
      timestamp: new Date(),
    }

    setCustomerMessages((prev) => [...prev, userMessage])
    const message = customerInput
    const currentFiles = [...selectedFiles]
    setCustomerInput("")
    setSelectedFiles([])
    setIsCustomerLoading(true)

    try {
      const formData = new FormData()
      formData.append("user_id", selectedUser.id)
      formData.append("vendor_id", selectedBusiness.id)
      formData.append("session_id", customerSessionId)
      formData.append("message", message)
      
      if (apiKey.trim()) {
        formData.append("api_key", apiKey)
      }

      currentFiles.forEach((file) => {
        formData.append("files", file)
      })

      const response = await fetch(`${BACKEND_URL}/api/v1/customer/chat`, {
        method: "POST",
        body: formData,
      })

      const data = await response.json()
      const aiMessage: ChatMessage = {
        id: (Date.now() + 1).toString(),
        content: data.message || "No response",
        sender: "ai",
        timestamp: new Date(),
      }
      setCustomerMessages((prev) => [...prev, aiMessage])
    } catch (error) {
      console.error("Error:", error)
      const errorMessage: ChatMessage = {
        id: (Date.now() + 1).toString(),
        content: `Error: ${error instanceof Error ? error.message : "Unknown error"}`,
        sender: "ai",
        timestamp: new Date(),
      }
      setCustomerMessages((prev) => [...prev, errorMessage])
    } finally {
      setIsCustomerLoading(false)
    }
  }

  // Business chat handlers
  const handleBusinessSend = async () => {
    if (!businessInput.trim() || !selectedBusiness) return

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      content: businessInput,
      sender: "user",
      timestamp: new Date(),
    }

    setBusinessMessages((prev) => [...prev, userMessage])
    const message = businessInput
    setBusinessInput("")
    setIsBusinessLoading(true)

    try {
      const response = await fetch(`${BACKEND_URL}/api/v1/business/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: businessReplyContext?.customerId || selectedUser?.id || "user-1",
          vendor_id: selectedBusiness.id,
          session_id: businessSessionId,
          sender: "business",
          message: message,
          product_name: businessReplyContext?.productName || "",
          product_price: "",
          message_type: "General",
          order_id: businessReplyContext?.orderId || undefined,
          api_key: apiKey || undefined,
        }),
      })

      const data = await response.json()
      const aiMessage: ChatMessage = {
        id: (Date.now() + 1).toString(),
        content: data.message || "No response",
        sender: "ai",
        timestamp: new Date(),
      }
      setBusinessMessages((prev) => [...prev, aiMessage])
    } catch (error) {
      console.error("Error:", error)
      setBusinessMessages((prev) => [...prev, { id: (Date.now() + 1).toString(), content: `Error: ${error instanceof Error ? error.message : "Unknown error"}`, sender: "ai", timestamp: new Date() }])
    } finally {
      setIsBusinessLoading(false)
    }
  }

  // Logistics chat handlers
  const handleLogisticsSend = async () => {
    if (!logisticsInput.trim() || !selectedLogistics) return

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      content: logisticsInput,
      sender: "user",
      timestamp: new Date(),
    }

    setLogisticsMessages((prev) => [...prev, userMessage])
    const message = logisticsInput
    setLogisticsInput("")
    setIsLogisticsLoading(true)

    try {
      const response = await fetch(`${BACKEND_URL}/api/v1/logistics/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: logisticsReplyContext?.customerId || selectedUser?.id || "user-1",
          vendor_id: selectedBusiness?.id || "business-1",
          logistic_id: selectedLogistics.id,
          session_id: logisticsSessionId,
          sender: "logistics",
          message: message,
          product_name: logisticsReplyContext?.productName || "",
          product_price: "",
          message_type: "Logistic planning",
          order_id: logisticsReplyContext?.orderId || undefined,
          api_key: apiKey || undefined,
        }),
      })

      const data = await response.json()
      const aiMessage: ChatMessage = {
        id: (Date.now() + 1).toString(),
        content: data.message || "No response",
        sender: "ai",
        timestamp: new Date(),
      }
      setLogisticsMessages((prev) => [...prev, aiMessage])
    } catch (error) {
      console.error("Error:", error)
      setLogisticsMessages((prev) => [...prev, { id: (Date.now() + 1).toString(), content: `Error: ${error instanceof Error ? error.message : "Unknown error"}`, sender: "ai", timestamp: new Date() }])
    } finally {
      setIsLogisticsLoading(false)
    }
  }

  // Analytics handlers
  const handleBusinessAnalytics = async () => {
    if (!selectedBusiness) {
      alert("Please select a business first")
      return
    }
    setIsLoadingAnalytics(true)
    try {
      const response = await fetch(`${BACKEND_URL}/api/v1/analytics/business`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          business_id: selectedBusiness.id,
          api_key: apiKey || undefined,
        }),
      })
      const data = await response.json()
      setBusinessAnalytics(data)
    } catch (error) {
      console.error("Error:", error)
    } finally {
      setIsLoadingAnalytics(false)
    }
  }

  const handleUserAnalytics = async () => {
    if (!selectedUser) {
      alert("Please select a user first")
      return
    }
    setIsLoadingAnalytics(true)
    try {
      const response = await fetch(`${BACKEND_URL}/api/v1/analytics/user`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: selectedUser.id,
          api_key: apiKey || undefined,
        }),
      })
      const data = await response.json()
      setUserAnalytics(data)
    } catch (error) {
      console.error("Error:", error)
    } finally {
      setIsLoadingAnalytics(false)
    }
  }

  const handleInventoryManagement = async () => {
    if (!selectedBusiness) {
      alert("Please select a business first")
      return
    }
    setIsLoadingAnalytics(true)
    try {
      const response = await fetch(`${BACKEND_URL}/api/v1/inventory/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          business_id: selectedBusiness.id,
          api_key: apiKey || undefined,
        }),
      })
      const data = await response.json()
      setInventoryData(data)
    } catch (error) {
      console.error("Error:", error)
    } finally {
      setIsLoadingAnalytics(false)
    }
  }

  const handleSupplyChain = async () => {
    if (!selectedBusiness) {
      alert("Please select a business first")
      return
    }
    setIsLoadingAnalytics(true)
    try {
      const response = await fetch(`${BACKEND_URL}/api/v1/supply-chain/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          business_id: selectedBusiness.id,
          api_key: apiKey || undefined,
        }),
      })
      const data = await response.json()
      setSupplyChainData(data)
    } catch (error) {
      console.error("Error:", error)
    } finally {
      setIsLoadingAnalytics(false)
    }
  }

  const canChat = selectedUser && selectedBusiness

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50">
      {/* Header */}
      <header className="bg-white shadow-lg border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex justify-between items-center">
            <div className="flex items-center space-x-3">
              <div className="flex items-center justify-center w-12 h-12 rounded-xl overflow-hidden bg-white">
                <img 
                  src="/ottobiz.png" 
                  alt="Ottobiz Logo" 
                  className="w-full h-full object-contain"
                />
              </div>
              <div>
                <h1 className="text-3xl font-bold bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">
                  Ottobiz
                </h1>
                <p className="text-sm text-gray-600">Automated Business Platform</p>
              </div>
            </div>
            <div className="flex items-center space-x-4">
              <div className="bg-white rounded-lg p-3 border border-gray-200">
                <div className="flex items-center space-x-2">
                  <Key className="w-4 h-4 text-gray-500" />
                  <input
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder="API Key (optional)"
                    className="text-sm border-none outline-none w-32"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {/* Persona Selection */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
          {/* User Persona */}
          <div className="bg-white rounded-lg shadow-md p-4">
            <div className="flex items-center space-x-2 mb-3">
              <Users className="w-5 h-5 text-blue-600" />
              <h3 className="font-semibold text-gray-800">User Persona</h3>
            </div>
            <div className="grid grid-cols-2 gap-2 max-h-32 overflow-y-auto">
              {predefinedUsers.map((user) => (
                <button
                  key={user.id}
                  onClick={() => { setSelectedUser(user); setCustomerSessionId(crypto.randomUUID()) }}
                  className={`p-2 rounded text-sm transition-all ${
                    selectedUser?.id === user.id
                      ? "bg-blue-500 text-white"
                      : "bg-gray-100 hover:bg-gray-200"
                  }`}
                >
                  {user.name}
                </button>
              ))}
            </div>
          </div>

          {/* Business Persona */}
          <div className="bg-white rounded-lg shadow-md p-4">
            <div className="flex items-center space-x-2 mb-3">
              <Building2 className="w-5 h-5 text-green-600" />
              <h3 className="font-semibold text-gray-800">Business Persona</h3>
            </div>
            <div className="grid grid-cols-2 gap-2 max-h-32 overflow-y-auto">
              {predefinedBusinesses.map((business) => (
                <button
                  key={business.id}
                  onClick={() => { setSelectedBusiness(business); setBusinessSessionId(crypto.randomUUID()); setCustomerSessionId(crypto.randomUUID()) }}
                  className={`p-2 rounded text-sm transition-all ${
                    selectedBusiness?.id === business.id
                      ? "bg-green-500 text-white"
                      : "bg-gray-100 hover:bg-gray-200"
                  }`}
                >
                  {business.name}
                </button>
              ))}
            </div>
          </div>

          {/* Logistics Persona */}
          <div className="bg-white rounded-lg shadow-md p-4">
            <div className="flex items-center space-x-2 mb-3">
              <Truck className="w-5 h-5 text-orange-600" />
              <h3 className="font-semibold text-gray-800">Logistics Persona</h3>
            </div>
            <div className="grid grid-cols-2 gap-2 max-h-32 overflow-y-auto">
              {predefinedLogistics.map((logistics) => (
                <button
                  key={logistics.id}
                  onClick={() => { setSelectedLogistics(logistics); setLogisticsSessionId(crypto.randomUUID()) }}
                  className={`p-2 rounded text-sm transition-all ${
                    selectedLogistics?.id === logistics.id
                      ? "bg-orange-500 text-white"
                      : "bg-gray-100 hover:bg-gray-200"
                  }`}
                >
                  {logistics.name}
                </button>
              ))}
          </div>
        </div>
      </div>

        {/* Chat Windows - Side by Side */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
          {/* Customer Chat */}
          <div className="bg-white rounded-lg shadow-xl border border-gray-200 h-[500px] flex flex-col">
            <div className="bg-blue-500 text-white p-3 rounded-t-lg flex items-center space-x-2">
              <User className="w-5 h-5" />
              <h3 className="font-semibold">Customer Chat</h3>
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-2">
              {customerMessages.map((msg) => (
                <div
                  key={msg.id}
                  className={`flex ${msg.sender === "user" ? "justify-end" : "justify-start"}`}
                >
                  <div
                    className={`max-w-[80%] px-3 py-2 rounded-lg text-sm ${
                      msg.sender === "user"
                        ? "bg-blue-500 text-white"
                          : "bg-gray-100 text-gray-800"
                      }`}
                    >
                    {msg.content}
                  </div>
                  </div>
                ))}
              {isCustomerLoading && (
                  <div className="flex justify-start">
                  <div className="bg-gray-100 px-3 py-2 rounded-lg text-sm">Thinking...</div>
                  </div>
                )}
              <div ref={customerMessagesEndRef} />
            </div>
            {/* File Preview */}
            {selectedFiles.length > 0 && (
              <div className="px-4 pb-2">
                <div className="flex flex-wrap gap-2">
                  {selectedFiles.map((file, index) => (
                    <div key={index} className="flex items-center space-x-2 bg-gray-100 rounded-lg px-2 py-1 text-xs">
                      {file.type.startsWith("image/") ? (
                        <ImageIcon className="w-3 h-3" />
                      ) : file.type === "application/pdf" ? (
                        <FileText className="w-3 h-3" />
                      ) : (
                        <Volume2 className="w-3 h-3" />
                      )}
                      <span className="truncate max-w-24">{file.name}</span>
                      <button
                        type="button"
                        onClick={() => removeFile(index)}
                        className="text-red-500 hover:text-red-700"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}
            <div className="border-t p-3">
              <div className="flex space-x-2">
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="p-2 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded transition-colors"
                  disabled={!canChat}
                >
                  <Paperclip className="w-4 h-4" />
                </button>
                <input
                  type="text"
                  value={customerInput}
                  onChange={(e) => setCustomerInput(e.target.value)}
                  onKeyPress={(e) => e.key === "Enter" && handleCustomerSend()}
                  placeholder={canChat ? "Type a message..." : "Select user & business first"}
                  className="flex-1 border rounded px-3 py-2 text-sm"
                  disabled={!canChat || isCustomerLoading}
                />
                <button
                  onClick={handleCustomerSend}
                  disabled={!canChat || isCustomerLoading || (!customerInput.trim() && selectedFiles.length === 0)}
                  className="bg-blue-500 text-white px-4 py-2 rounded disabled:opacity-50"
                >
                  <Send className="w-4 h-4" />
                </button>
              </div>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept="image/*,audio/*,.pdf,.doc,.docx,.txt"
              onChange={handleFileSelect}
              className="hidden"
            />
              </div>

          {/* Business Chat */}
          <div className="bg-white rounded-lg shadow-xl border border-gray-200 h-[500px] flex flex-col">
            <div className="bg-green-500 text-white p-3 rounded-t-lg flex items-center space-x-2">
              <Building2 className="w-5 h-5" />
              <h3 className="font-semibold">Business Chat</h3>
            </div>
            {businessReplyContext && (
              <div className="px-4 py-1 bg-green-50 border-b text-xs text-green-700 flex items-center justify-between">
                <span>Replying to: {businessReplyContext.customerId}{businessReplyContext.productName ? ` · ${businessReplyContext.productName}` : ""}</span>
                <button type="button" onClick={() => setBusinessReplyContext(null)} className="text-green-600 hover:underline">Clear</button>
              </div>
            )}
            <div className="flex-1 overflow-y-auto p-4 space-y-2">
              {businessMessages.map((msg) => (
                <div
                  key={msg.id}
                  className={`flex ${msg.sender === "user" ? "justify-end" : "justify-start"}`}
                >
                  <div
                    className={`max-w-[80%] px-3 py-2 rounded-lg text-sm ${
                      msg.sender === "user"
                        ? "bg-green-500 text-white"
                        : "bg-gray-100 text-gray-800"
                    } ${msg.customer_id ? "cursor-pointer hover:ring-2 hover:ring-green-300" : ""}`}
                    onClick={msg.customer_id ? () => setBusinessReplyContext({ customerId: msg.customer_id!, productName: msg.product_name, orderId: msg.order_id }) : undefined}
                    role={msg.customer_id ? "button" : undefined}
                  >
                    {msg.content}
                  </div>
                </div>
              ))}
              {isBusinessLoading && (
                <div className="flex justify-start">
                  <div className="bg-gray-100 px-3 py-2 rounded-lg text-sm">Thinking...</div>
                </div>
              )}
              <div ref={businessMessagesEndRef} />
            </div>
            <div className="border-t p-3">
              <div className="flex space-x-2">
                  <input
                    type="text"
                  value={businessInput}
                  onChange={(e) => setBusinessInput(e.target.value)}
                  onKeyPress={(e) => e.key === "Enter" && handleBusinessSend()}
                  placeholder={selectedBusiness ? "Type a message..." : "Select business first"}
                  className="flex-1 border rounded px-3 py-2 text-sm"
                  disabled={!selectedBusiness || isBusinessLoading}
                  />
                  <button
                  onClick={handleBusinessSend}
                  disabled={!selectedBusiness || isBusinessLoading}
                  className="bg-green-500 text-white px-4 py-2 rounded disabled:opacity-50"
                >
                  <Send className="w-4 h-4" />
                  </button>
              </div>
            </div>
          </div>

          {/* Logistics Chat */}
          <div className="bg-white rounded-lg shadow-xl border border-gray-200 h-[500px] flex flex-col">
            <div className="bg-orange-500 text-white p-3 rounded-t-lg flex items-center space-x-2">
              <Truck className="w-5 h-5" />
              <h3 className="font-semibold">Logistics Chat</h3>
            </div>
            {logisticsReplyContext && (
              <div className="px-4 py-1 bg-orange-50 border-b text-xs text-orange-700 flex items-center justify-between">
                <span>Replying to: {logisticsReplyContext.customerId}{logisticsReplyContext.productName ? ` · ${logisticsReplyContext.productName}` : ""}</span>
                <button type="button" onClick={() => setLogisticsReplyContext(null)} className="text-orange-600 hover:underline">Clear</button>
              </div>
            )}
            <div className="flex-1 overflow-y-auto p-4 space-y-2">
              {logisticsMessages.map((msg) => (
                <div
                  key={msg.id}
                  className={`flex ${msg.sender === "user" ? "justify-end" : "justify-start"}`}
                >
                  <div
                    className={`max-w-[80%] px-3 py-2 rounded-lg text-sm ${
                      msg.sender === "user"
                        ? "bg-orange-500 text-white"
                        : "bg-gray-100 text-gray-800"
                    } ${msg.customer_id ? "cursor-pointer hover:ring-2 hover:ring-orange-300" : ""}`}
                    onClick={msg.customer_id ? () => setLogisticsReplyContext({ customerId: msg.customer_id!, productName: msg.product_name, orderId: msg.order_id }) : undefined}
                    role={msg.customer_id ? "button" : undefined}
                  >
                    {msg.content}
                  </div>
                </div>
              ))}
              {isLogisticsLoading && (
                <div className="flex justify-start">
                  <div className="bg-gray-100 px-3 py-2 rounded-lg text-sm">Thinking...</div>
              </div>
              )}
              <div ref={logisticsMessagesEndRef} />
            </div>
            <div className="border-t p-3">
              <div className="flex space-x-2">
                <input
                  type="text"
                  value={logisticsInput}
                  onChange={(e) => setLogisticsInput(e.target.value)}
                  onKeyPress={(e) => e.key === "Enter" && handleLogisticsSend()}
                  placeholder={selectedLogistics ? "Type a message..." : "Select logistics first"}
                  className="flex-1 border rounded px-3 py-2 text-sm"
                  disabled={!selectedLogistics || isLogisticsLoading}
                />
                <button
                  onClick={handleLogisticsSend}
                  disabled={!selectedLogistics || isLogisticsLoading}
                  className="bg-orange-500 text-white px-4 py-2 rounded disabled:opacity-50"
                >
                  <Send className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>
            </div>

        {/* Analytics Sections */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Business Analytics */}
          <div className="bg-white rounded-lg shadow-md p-4">
              <div className="flex items-center space-x-2 mb-3">
              <BarChart3 className="w-5 h-5 text-purple-600" />
              <h3 className="font-semibold text-gray-800">Business Analytics</h3>
              </div>
              <button
              onClick={handleBusinessAnalytics}
              disabled={!selectedBusiness || isLoadingAnalytics}
              className="w-full bg-purple-500 text-white py-2 rounded disabled:opacity-50 mb-3"
            >
              Get Analytics
              </button>
            {businessAnalytics && (
              <div className="bg-gray-50 rounded p-2 text-xs max-h-32 overflow-y-auto">
                <pre>{JSON.stringify(businessAnalytics, null, 2)}</pre>
                </div>
              )}
            </div>

            {/* User Analytics */}
          <div className="bg-white rounded-lg shadow-md p-4">
              <div className="flex items-center space-x-2 mb-3">
              <TrendingUp className="w-5 h-5 text-blue-600" />
              <h3 className="font-semibold text-gray-800">User Analytics</h3>
            </div>
            <button
              onClick={handleUserAnalytics}
              disabled={!selectedUser || isLoadingAnalytics}
              className="w-full bg-blue-500 text-white py-2 rounded disabled:opacity-50 mb-3"
            >
              Get Analytics
            </button>
            {userAnalytics && (
              <div className="bg-gray-50 rounded p-2 text-xs max-h-32 overflow-y-auto">
                <pre>{JSON.stringify(userAnalytics, null, 2)}</pre>
              </div>
            )}
          </div>

          {/* Inventory Management */}
          <div className="bg-white rounded-lg shadow-md p-4">
            <div className="flex items-center space-x-2 mb-3">
              <Package className="w-5 h-5 text-green-600" />
              <h3 className="font-semibold text-gray-800">Inventory</h3>
              </div>
              <button
              onClick={handleInventoryManagement}
              disabled={!selectedBusiness || isLoadingAnalytics}
              className="w-full bg-green-500 text-white py-2 rounded disabled:opacity-50 mb-3"
            >
              Get Inventory
              </button>
            {inventoryData && (
              <div className="bg-gray-50 rounded p-2 text-xs max-h-32 overflow-y-auto">
                <pre>{JSON.stringify(inventoryData, null, 2)}</pre>
                </div>
              )}
          </div>

          {/* Supply Chain */}
          <div className="bg-white rounded-lg shadow-md p-4">
            <div className="flex items-center space-x-2 mb-3">
              <Truck className="w-5 h-5 text-orange-600" />
              <h3 className="font-semibold text-gray-800">Supply Chain</h3>
            </div>
            <button
              onClick={handleSupplyChain}
              disabled={!selectedBusiness || isLoadingAnalytics}
              className="w-full bg-orange-500 text-white py-2 rounded disabled:opacity-50 mb-3"
            >
              Get Supply Chain
            </button>
            {supplyChainData && (
              <div className="bg-gray-50 rounded p-2 text-xs max-h-32 overflow-y-auto">
                <pre>{JSON.stringify(supplyChainData, null, 2)}</pre>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
