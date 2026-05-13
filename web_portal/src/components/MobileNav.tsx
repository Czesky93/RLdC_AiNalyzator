'use client'

interface MobileNavProps {
	activeView: string
	setActiveView: (view: string) => void
}

const mobileItems = [
	{ id: 'dashboard', label: 'Panel' },
	{ id: 'trade-desk', label: 'Handel' },
	{ id: 'portfolio', label: 'Portfel' },
	{ id: 'telegram-intel', label: 'Telegram' },
	{ id: 'operator-console', label: 'Diagnostyka' },
]

export default function MobileNav({ activeView, setActiveView }: MobileNavProps) {
	return (
		<div className="md:hidden fixed bottom-0 left-0 right-0 z-40 border-t border-rldc-dark-border bg-[#0b121a]/95 backdrop-blur-sm">
			<div className="grid grid-cols-5">
				{mobileItems.map((item) => {
					const isActive = activeView === item.id
					return (
						<button
							key={item.id}
							type="button"
							onClick={() => setActiveView(item.id)}
							className={`py-2 text-[10px] font-semibold transition ${isActive ? 'text-teal-primary' : 'text-slate-400'}`}
						>
							{item.label}
						</button>
					)
				})}
			</div>
		</div>
	)
}