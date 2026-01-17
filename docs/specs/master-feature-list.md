# ARGO Master Feature List

**Purpose:** This document defines the complete scope of ARGO capabilities. It is canonical—the boundary of what ARGO is designed to do.

**Status:** Not all items are implemented. This list defines what *will* be possible, not what is currently available. Version 0.9.0 includes memory, preferences, recall mode, and conversation browsing.

**Reading this:** Items are grouped by domain. Each item represents one distinct capability or safety constraint. The numbering is intentional and preserves scope.

---

## ROOM-TO-ROOM PRESENCE

1. Continuous voice availability across rooms
2. Active room detection based on last speaker
3. Seamless conversation handoff between rooms
4. No wake word once authenticated
5. Per-room mic priority handling
6. Silent rooms remain silent

## VOICE CONTROL

7. Natural language commands
8. Interruptible speech
9. Command vs conversation detection
10. Confirmation required for actions
11. Voiceprint authentication
12. Multiple user profiles
13. Guest mode with restrictions

## LIGHTING CONTROL

14. Lights on/off per room
15. Brightness control
16. Color temperature control
17. RGB lighting control
18. Scene presets
19. Whole-house lighting commands
20. Time-based lighting routines
21. Motion-triggered lighting
22. Manual switch override respected

## CLIMATE CONTROL

23. Per-room temperature control
24. Whole-house temperature control
25. Mode control (heat/cool/auto/off)
26. Fan speed control
27. Humidity awareness
28. Night temperature profiles
29. Natural language temperature adjustment
30. Energy-saving modes
31. Manual thermostat override respected

## MEDIA CONTROL – AUDIO

32. Play music per room
33. Sync music across rooms
34. Unsync rooms on demand
35. Volume per room
36. Global volume control
37. Play from local MP3 library
38. Playlist generation by mood or genre
39. Resume playback on room entry
40. Stop playback on room exit
41. Speaker group management

## MEDIA CONTROL – VIDEO

42. Turn TVs on/off
43. Switch HDMI inputs
44. Launch streaming apps
45. Play/pause/skip control
46. TV volume control
47. Display generated images
48. Display documents or specs
49. Screen follows active room
50. Manual remote override respected

## VISUAL OUTPUT

51. Display images on nearest screen
52. Display system dashboards
53. Display camera feeds
54. Display diagrams
55. Display code when requested
56. Auto-dismiss visuals

## VISION & CAMERAS

57. Camera activation on request only
58. Object recognition (labels only)
59. Authorized face recognition
60. Basic gesture recognition
61. Room occupancy detection
62. No recording without command
63. No cloud upload by default

## SMART DEVICES

64. Smart plug control
65. Fan control
66. Air purifier control
67. Humidifier/dehumidifier control
68. Robot vacuum control
69. Robot mop control
70. Smart lock control (confirmation required)
71. Appliance status queries

## KITCHEN & UTILITIES

72. Timer creation
73. Multiple timers
74. Named timers
75. Timers announce in active room
76. Hands-free kitchen mode
77. Appliance reminders
78. Fridge inventory queries
79. Recipe assistance
80. Safety reminders

## NOTIFICATIONS

81. Delivery announcements
82. Doorbell announcements
83. Alarm announcements
84. Quiet-hour suppression
85. Priority escalation
86. Per-room routing

## AUTOMATION

87. Daily routines
88. Weekly routines
89. Event-based automations
90. Presence-based automations
91. Manual routine triggers
92. Temporary overrides
93. Vacation mode
94. Emergency mode

## PERSONALIZATION

95. User profiles
96. Room profiles
97. Time-of-day behavior shifts
98. Mood-based behavior
99. Media preferences per user
100. Temperature preferences per user

## APPLICATION CONTROL

101. Open applications
102. Close applications
103. Switch applications
104. Focus windows
105. Control apps by name
106. Read application state
107. Manual user control overrides ARGO

## DOCUMENT CREATION & EDITING

108. Create Word documents
109. Open Word documents
110. Dictate text
111. Write structured documents
112. Edit existing text
113. Insert formatting
114. Navigate documents by voice
115. Save to specified location
116. Never overwrite without confirmation
117. Export DOCX or PDF

## EMAIL CONTROL

118. Open email client
119. Read inbox summaries
120. Read emails aloud
121. Search emails
122. Draft emails
123. Rewrite emails
124. Attach files (confirmation required)
125. Explicit recipient setting
126. Display full email before sending
127. Explicit send confirmation
128. Send email
129. Log sent email metadata
130. Never auto-send

## WRITING MODES

131. Dictation mode
132. Assisted writing mode
133. Rewrite-only mode
134. Summarize-only mode
135. Tone adjustment mode
136. Screen read-back mode

## FILE & DATA ACCESS

137. Search local files
138. Open files
139. Summarize documents
140. Compare documents
141. Export summaries
142. Never delete without confirmation

## SYSTEM AWARENESS

143. CPU usage queries
144. GPU usage queries
145. Disk usage queries
146. Network status queries
147. Printer status queries
148. Camera status queries
149. Sensor health checks

## 3D PRINTER CONTROL

150. Printer status reporting
151. Temperature monitoring
152. Start print (confirmation required)
153. Pause print
154. Resume print
155. Emergency stop
156. Camera feed display
157. Print completion alerts

## MEMORY & CONTEXT

158. Cross-room conversation continuity
159. Explicit memory storage only
160. Project-scoped memory
161. Preference memory
162. Decision memory
163. Memory review and deletion

## SECURITY & SAFETY

164. Voice authentication enforcement
165. Permission levels per action
166. Full audit logs
167. Replayable command history
168. No silent execution
169. Fail-closed behavior
170. Manual kill switch

## NETWORK ARCHITECTURE

171. Single ARGO core
172. Multiple room clients
173. Clients have zero authority
174. Local-first operation
175. Offline capable
176. Cloud optional and gated

## MODES

177. Home mode
178. Work mode
179. Night mode
180. Guest mode
181. Emergency mode
182. Silent mode
183. Demo mode

## EXPLICIT NON-BEHAVIOR

184. No unsolicited actions
185. No intent guessing
186. No auto memory saving
187. No background chatter
188. No cloud dependency
189. No autonomous outreach
190. No pretending actions occurred
191. No silent edits
192. No silent sends
193. No silent executions
194. No hidden learning
195. No model drift without approval
196. No override of physical controls
197. No bypassing confirmations
198. No background monitoring
199. No recording by default
200. No authority escalation
