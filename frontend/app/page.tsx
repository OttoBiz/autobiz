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
}

interface Persona {
  id: string
  name: string
}

const predefinedUsers: Persona[] = [
  { id: "user-1", name: "John Doe" },
  { id: "user-2", name: "Sarah Johnson" },
  { id: "user-3", name: "Michael Chen" },
  { id: "user-4", name: "Emily Rodriguez" },
  { id: "user-5", name: "David Wilson" },
  { id: "user-6", name: "Lisa Thompson" },
]

const predefinedBusinesses: Persona[] = [
  { id: "business-1", name: "Donrey Fashion" },
  { id: "business-2", name: "Junae Cosmetics" },
  { id: "business-3", name: "Manny Gadgets" },
  { id: "business-4", name: "Tesla Tech" },
  { id: "business-5", name: "Kemi Surprises" },
]

const predefinedLogistics: Persona[] = [
  { id: "logistics-1", name: "Fast Delivery Co" },
  { id: "logistics-2", name: "Express Logistics" },
  { id: "logistics-3", name: "Quick Ship" },
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

  // Customer chat handlers
  const handleCustomerSend = async () => {
    if (!customerInput.trim() || !selectedUser || !selectedBusiness) return

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      content: customerInput,
      sender: "user",
      timestamp: new Date(),
    }

    setCustomerMessages((prev) => [...prev, userMessage])
    const message = customerInput
    setCustomerInput("")
    setIsCustomerLoading(true)

    try {
      const response = await fetch(`${BACKEND_URL}/api/v1/customer/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: selectedUser.id,
          vendor_id: selectedBusiness.id,
          session_id: `session-${Date.now()}`,
          message: message,
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
          user_id: selectedUser?.id || "user-1",
          vendor_id: selectedBusiness.id,
          session_id: `session-${Date.now()}`,
          sender: "business",
          message: message,
          product_name: "",
          product_price: "",
          message_type: "General",
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
          user_id: selectedUser?.id || "user-1",
          vendor_id: selectedBusiness?.id || "business-1",
          logistic_id: selectedLogistics.id,
          session_id: `session-${Date.now()}`,
          sender: "logistics",
          message: message,
          product_name: "",
          product_price: "",
          message_type: "Logistic planning",
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
              <div className="flex items-center justify-center w-12 h-12 bg-gradient-to-r from-blue-500 to-purple-600 rounded-xl">
                <ShoppingCart className="w-6 h-6 text-white" />
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
                  onClick={() => setSelectedUser(user)}
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
                  onClick={() => setSelectedBusiness(business)}
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
                  onClick={() => setSelectedLogistics(logistics)}
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
            <div className="border-t p-3">
              <div className="flex space-x-2">
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
                  disabled={!canChat || isCustomerLoading}
                  className="bg-blue-500 text-white px-4 py-2 rounded disabled:opacity-50"
                >
                  <Send className="w-4 h-4" />
                </button>
              </div>
            </div>
              </div>

          {/* Business Chat */}
          <div className="bg-white rounded-lg shadow-xl border border-gray-200 h-[500px] flex flex-col">
            <div className="bg-green-500 text-white p-3 rounded-t-lg flex items-center space-x-2">
              <Building2 className="w-5 h-5" />
              <h3 className="font-semibold">Business Chat</h3>
            </div>
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
                    }`}
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
                    }`}
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
