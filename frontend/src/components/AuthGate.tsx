import * as React from 'react'
import {
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
} from 'firebase/auth'
import { auth } from '../services/firebase'
import { useToast } from '@/components/ui/Toast'

export function AuthGate() {
  const [isSignUp, setIsSignUp] = React.useState(false)
  const [email, setEmail] = React.useState('')
  const [password, setPassword] = React.useState('')
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const { toast } = useToast()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email || !password) {
      setError('Please fill in all fields')
      return
    }

    setLoading(true)
    setError(null)

    try {
      if (isSignUp) {
        await createUserWithEmailAndPassword(auth, email, password)
        toast({
          title: 'Account Created',
          description: 'Your account was successfully created and signed in.',
          type: 'success',
        })
      } else {
        await signInWithEmailAndPassword(auth, email, password)
        toast({
          title: 'Welcome Back',
          description: 'Successfully signed in.',
          type: 'success',
        })
      }
    } catch (err: any) {
      console.error(err)
      let displayError = err.message || 'Authentication failed. Please check your credentials.'
      if (err.code === 'auth/user-not-found' || err.code === 'auth/wrong-password' || err.code === 'auth/invalid-credential') {
        displayError = 'Invalid email or password.'
      } else if (err.code === 'auth/email-already-in-use') {
        displayError = 'This email is already registered.'
      } else if (err.code === 'auth/weak-password') {
        displayError = 'Password should be at least 6 characters.'
      } else if (err.code === 'auth/invalid-email') {
        displayError = 'Please enter a valid email address.'
      }
      setError(displayError)
      toast({
        title: 'Authentication Error',
        description: displayError,
        type: 'error',
      })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-screen w-screen items-center justify-center bg-zinc-50 font-sans text-zinc-800 dark:bg-zinc-950 dark:text-zinc-100 transition-colors duration-300">
      <div className="w-full max-w-md px-6 py-8 border border-zinc-200 dark:border-zinc-900 rounded-2xl bg-white/80 dark:bg-zinc-950/80 backdrop-blur-md shadow-2xl space-y-6">
        <div className="text-center space-y-2">
          <h1 className="text-2xl font-bold tracking-tight text-blue-600 dark:text-blue-500">
            Chatbot GCP
          </h1>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            {isSignUp
              ? 'Create an account to get started'
              : 'Sign in to access your chatbot'}
          </p>
        </div>

        {error && (
          <div className="p-3.5 text-xs rounded-xl bg-rose-50 dark:bg-rose-950/30 text-rose-600 dark:text-rose-400 border border-rose-100 dark:border-rose-950/50 animate-pulse">
            ⚠️ {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider">
              Email Address
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="name@example.com"
              disabled={loading}
              className="w-full px-4 py-2.5 text-sm rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 focus:outline-hidden focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 dark:focus:border-blue-500 transition-all duration-200 disabled:opacity-50"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider">
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              disabled={loading}
              className="w-full px-4 py-2.5 text-sm rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 focus:outline-hidden focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 dark:focus:border-blue-500 transition-all duration-200 disabled:opacity-50"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-medium text-sm transition-all duration-200 flex items-center justify-center shadow-lg hover:shadow-blue-600/10 cursor-pointer disabled:opacity-50"
          >
            {loading ? (
              <svg className="animate-spin h-5 w-5 text-white" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            ) : isSignUp ? (
              'Sign Up'
              ) : (
              'Sign In'
            )}
          </button>
        </form>

        <div className="relative flex items-center justify-center">
          <div className="absolute inset-0 border-t border-zinc-200 dark:border-zinc-900" />
          <span className="relative px-3 text-xs bg-white dark:bg-zinc-950 text-zinc-400 uppercase tracking-wider font-semibold">
            Or
          </span>
        </div>

        <div className="text-center">
          <button
            onClick={() => {
              setIsSignUp(!isSignUp)
              setError(null)
            }}
            disabled={loading}
            className="text-xs font-semibold text-zinc-650 hover:text-blue-600 dark:text-zinc-350 dark:hover:text-blue-400 transition-colors duration-150 cursor-pointer"
          >
            {isSignUp ? 'Already have an account? Sign In' : "Don't have an account? Sign Up"}
          </button>
        </div>
      </div>
    </div>
  )
}
