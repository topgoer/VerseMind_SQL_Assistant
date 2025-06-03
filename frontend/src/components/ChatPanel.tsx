import React, { useState, useRef, useEffect } from 'react';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from './ui/card';
import { Textarea } from './ui/textarea';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/tabs';
import { Resizable } from 're-resizable';
import { Send, Download } from 'lucide-react';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

interface ChatPanelProps {
  mode: 'chat' | 'mcp';
}

type Strategy = 'base' | 'strict' | 'cite';

const ChatPanel: React.FC<ChatPanelProps> = ({ mode }) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [jwtToken, setJwtToken] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sqlQuery, setSqlQuery] = useState('');
  const [results, setResults] = useState<any[] | null>(null);
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);
  const [mcpTrace, setMcpTrace] = useState<object | null>(null);
  const [promptSql, setPromptSql] = useState(''); // Renamed from prompt
  const [promptAnswer, setPromptAnswer] = useState(''); // New state for answer prompt
  const [strategy, setStrategy] = useState<Strategy>('base'); // New state for strategy
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Strategy descriptions
  const strategyDescriptions = {
    base: 'Standard context-based generation with comprehensive responses.',
    strict: 'Explicit disclaimers if the answer cannot be found in the provided context.',
    cite: 'Requires references to specific context lines used in generating the response.'
  };

  // Helper function to format cell values safely
  const formatCellValue = (value: any): string => {
    if (value === null || value === undefined) {
      return '';
    }
    if (typeof value === 'object') {
      return JSON.stringify(value);
    }
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      return String(value);
    }
    return String(value);
  };

  // Scroll to bottom of messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Load JWT token from localStorage
  useEffect(() => {
    const savedToken = localStorage.getItem('jwt_token');
    if (savedToken) {
      setJwtToken(savedToken);
    }
  }, []);

  const handleSendMessage = async () => {
    if (!input.trim() || !jwtToken) return;

    // Save JWT token
    localStorage.setItem('jwt_token', jwtToken);

    // Add user message
    setMessages([...messages, { id: crypto.randomUUID(), role: 'user', content: input }]);
    setIsLoading(true);
    // Clear previous results for new query
    setSqlQuery('');
    setResults(null);
    setDownloadUrl(null);
    setMcpTrace(null);
    setPromptSql('');
    setPromptAnswer('');

    try {
      if (mode === 'chat') {
        // Call /chat endpoint with absolute URL
        const response = await fetch('http://localhost:8001/chat', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${jwtToken}`
          },
          body: JSON.stringify({ 
            query: input,
            strategy: strategy 
          })
        });

        if (!response.ok) {
          throw new Error(`Error: ${response.status}`);
        }

        const data = await response.json();
        
        // Log the entire data object and specific prompt fields for debugging
        console.log("Received data from /chat endpoint:", JSON.stringify(data, null, 2));
        console.log("Prompt SQL from data:", data.prompt_sql);
        console.log("Prompt Answer from data:", data.prompt_answer);
        
        // Update state with response
        setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'assistant', content: data.answer }]);
        setSqlQuery(data.sql ?? '');
        setResults(data.rows ?? null);
        setDownloadUrl(data.download_url ?? null);
        setPromptSql(data.prompt_sql ?? ''); // Use prompt_sql
        setPromptAnswer(data.prompt_answer ?? ''); // Use prompt_answer
        setMcpTrace(null);
      } else {
        // Call /mcp endpoint with absolute URL
        const response = await fetch('http://localhost:8001/mcp', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${jwtToken}`
          },
          body: JSON.stringify({
            trace_id: crypto.randomUUID(),
            context: { query: input },
            steps: [
              { tool: 'llm_nl_to_sql' },
              { tool: 'sql_exec' },
              { tool: 'answer_format' }
            ]
          })
        });

        if (!response.ok) {
          throw new Error(`Error: ${response.status}`);
        }

        const data = await response.json();
        // Log the entire data object for MCP mode as well
        console.log("Received data from /mcp endpoint:", JSON.stringify(data, null, 2));
        
        // Extract data from MCP response
        const llmNlToSqlStep = data.steps.find((s: any) => s.tool === 'llm_nl_to_sql');
        const sqlExecStep = data.steps.find((s: any) => s.tool === 'sql_exec');
        const answerStep = data.steps.find((s: any) => s.tool === 'answer_format');
        
        // Update state with response
        setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'assistant', content: answerStep?.output ?? 'No answer generated' }]);
        setSqlQuery(llmNlToSqlStep?.output?.sql ?? '');
        setResults(sqlExecStep?.output?.rows ?? null);
        setDownloadUrl(sqlExecStep?.output?.download_url ?? null);
        setPromptSql(llmNlToSqlStep?.output?.prompt ?? ''); // Set SQL prompt
        setPromptAnswer(input); // Use the original user query as the answer prompt for MCP
        setMcpTrace(data);
      }
    } catch (error) {
      console.error('Error:', error);
      setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'assistant', content: `Error: ${error instanceof Error ? error.message : 'Unknown error'}` }]);
    } finally {
      setIsLoading(false);
      setInput('');
    }
  };

  return (
    <Resizable
      defaultSize={{ width: '100%', height: '65vh' }} // Changed to vh
      minHeight={300}
      maxHeight="90vh" // Changed to vh
      enable={{ top: true, bottom: true }}
      className="border rounded-lg shadow-md bg-white"
    >
      <Card className="h-full flex flex-col">
        <CardHeader className="pb-2">
          <CardTitle>{mode === 'chat' ? 'SQL Assistant' : 'MCP Service'}</CardTitle>
          <div className="mt-2">
            <Input
              placeholder="Enter JWT token with fleet_id claim"
              value={jwtToken}
              onChange={(e) => setJwtToken(e.target.value)}
              className="mb-2"
            />
            
            {/* Strategy Selection */}
            <div className="mt-3 p-3 border rounded-lg bg-gray-50">
              <fieldset>
                <legend className="text-sm font-medium text-gray-700 mb-2">Query Generation Strategy:</legend>
                <div className="flex flex-wrap gap-4 mb-2">
                  <label className="flex items-center space-x-2 cursor-pointer">
                    <input
                      type="radio"
                      name="strategy"
                      value="base"
                      checked={strategy === 'base'}
                      onChange={(e) => setStrategy(e.target.value as Strategy)}
                      className="text-blue-600 focus:ring-blue-500"
                    />
                    <span className="text-sm">Base</span>
                  </label>
                  <label className="flex items-center space-x-2 cursor-pointer">
                    <input
                      type="radio"
                      name="strategy"
                      value="strict"
                      checked={strategy === 'strict'}
                      onChange={(e) => setStrategy(e.target.value as Strategy)}
                      className="text-blue-600 focus:ring-blue-500"
                    />
                    <span className="text-sm">Strict</span>
                  </label>
                  <label className="flex items-center space-x-2 cursor-pointer">
                    <input
                      type="radio"
                      name="strategy"
                      value="cite"
                      checked={strategy === 'cite'}
                      onChange={(e) => setStrategy(e.target.value as Strategy)}
                      className="text-blue-600 focus:ring-blue-500"
                    />
                    <span className="text-sm">Citation</span>
                  </label>
                </div>
                <div className="text-xs text-gray-600 italic">
                  {strategyDescriptions[strategy]}
                </div>
              </fieldset>
            </div>
          </div>
        </CardHeader>
        
        <div className="flex-grow flex flex-col min-h-0">
          <Resizable
            defaultSize={{ width: '100%', height: '55%' }}
            minHeight={150}
            maxHeight="85%"
            enable={{ bottom: true }}
            className="border-b-2 border-gray-200"
            handleStyles={{
              bottom: {
                cursor: 'row-resize',
                height: '6px',
                backgroundColor: 'transparent',
                borderBottom: '2px solid #e5e7eb',
                transition: 'border-color 0.2s ease'
              }
            }}
            handleClasses={{
              bottom: 'hover:border-blue-400'
            }}
          >
            <CardContent className="h-full overflow-auto p-4">
              <div className="space-y-4">
                {messages.map((message) => (
                  <div 
                    key={message.id} 
                    className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
                  >
                    <div 
                      className={`max-w-[80%] rounded-lg p-3 ${
                        message.role === 'user' 
                          ? 'bg-blue-500 text-white' 
                          : 'bg-gray-100 text-gray-800'
                      }`}
                    >
                      {message.content}
                    </div>
                  </div>
                ))}
                {isLoading && (
                  <div className="flex justify-start">
                    <div className="max-w-[80%] rounded-lg p-3 bg-gray-100">
                      <div className="flex items-center space-x-2">
                        <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></div>
                        <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></div>
                        <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></div>
                      </div>
                    </div>
                  </div>
                )}
                <div ref={messagesEndRef} />
              </div>
            </CardContent>
          </Resizable>
          
          <div className="flex-grow px-4 py-3 min-h-0 bg-gray-50">
            {(sqlQuery || results || downloadUrl || mcpTrace || promptSql || promptAnswer) && (
              <div className="h-full bg-white rounded-lg border shadow-sm">
                <Tabs defaultValue="sql" className="w-full h-full flex flex-col">
                  <TabsList className="m-2 mb-0"> {/* Added margin for better spacing */}
                    <TabsTrigger value="sql">SQL</TabsTrigger>
                    <TabsTrigger value="results">Results</TabsTrigger>
                    <TabsTrigger value="promptSql">Prompt (SQL)</TabsTrigger>
                    <TabsTrigger value="promptAnswer">Prompt (Answer)</TabsTrigger>
                    {mode === 'mcp' && <TabsTrigger value="trace">MCP Trace</TabsTrigger>}
                    {downloadUrl && <TabsTrigger value="download">Download</TabsTrigger>}
                  </TabsList>
                  
                  <div className="flex-grow m-2 mt-2 overflow-y-auto">
                    <TabsContent value="sql" className="h-full">
                      <Textarea 
                        value={sqlQuery} 
                        readOnly 
                        className="font-mono text-sm w-full h-full resize-none border-0 focus:ring-0"
                      />
                    </TabsContent>
                  
                  <TabsContent value="promptSql" className="h-full">
                    <Textarea 
                      value={promptSql} 
                      readOnly 
                      className="font-mono text-sm w-full h-full resize-none border-0 focus:ring-0"
                    />
                  </TabsContent>
                  
                  <TabsContent value="promptAnswer" className="h-full">
                    <Textarea 
                      value={promptAnswer} 
                      readOnly 
                      className="font-mono text-sm w-full h-full resize-none border-0 focus:ring-0"
                    />
                  </TabsContent>
                  
                  <TabsContent value="results" className="h-full">
                    {(() => {
                      if (results && results.length > 0 && results[0] && typeof results[0] === 'object') {
                        return (
                          <div className="w-full h-full overflow-auto">
                            <table className="min-w-full divide-y divide-gray-200">
                              <thead className="bg-gray-50 sticky top-0"> {/* Made header sticky */}
                                <tr>
                                  {Object.keys(results[0]).map((key) => (
                                    <th 
                                      key={key}
                                      className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                                    >
                                      {key}
                                    </th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody className="bg-white divide-y divide-gray-200">
                                {results.map((row) => {
                                  // Create a stable composite key using row values
                                  const rowKey = row && typeof row === 'object' ? 
                                    `row-${JSON.stringify(row).substring(0, 100)}` : `row-${crypto.randomUUID()}`;
                                    
                                  return (
                                    <tr key={rowKey}>
                                      {row && typeof row === 'object' && Object.entries(row).map(([key, value]) => (
                                        <td key={`${rowKey}-${key}`} className="px-3 py-2 text-sm text-gray-500">
                                          {formatCellValue(value)}
                                        </td>
                                      ))}
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          </div>
                        );
                      } else if (downloadUrl) {
                        return (
                          <div className="text-center p-4">
                            <p>Large result set available for download</p>
                          </div>
                        );
                      } else {
                        return (
                          <div className="text-center p-4">No results available</div>
                        );
                      }
                    })()}
                  </TabsContent>
                  
                  {mode === 'mcp' && (
                    <TabsContent value="trace" className="h-full">
                      <Textarea 
                        value={mcpTrace ? JSON.stringify(mcpTrace, null, 2) : ''} 
                        readOnly 
                        className="font-mono text-sm w-full h-full resize-none border-0 focus:ring-0"
                      />
                    </TabsContent>
                  )}
                  
                  {downloadUrl && (
                    <TabsContent value="download" className="h-full">
                      <div className="flex justify-center items-center w-full h-full">
                        <a 
                          href={downloadUrl} 
                          download 
                          className="flex items-center space-x-2 bg-blue-500 text-white px-4 py-2 rounded-md hover:bg-blue-600"
                        >
                          <Download size={16} />
                          <span>Download CSV</span>
                        </a>
                      </div>
                    </TabsContent>
                  )}
                  </div>
                </Tabs>
              </div>
            )}
          </div>
        </div>
        
        <CardFooter className="flex items-center space-x-2 pt-2">
          <Input
            placeholder="Ask a question about your fleet..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
            disabled={isLoading}
          />
          <Button 
            onClick={handleSendMessage} 
            disabled={isLoading || !input.trim() || !jwtToken}
            size="icon"
          >
            <Send size={16} />
          </Button>
        </CardFooter>
      </Card>
    </Resizable>
  );
};

export default ChatPanel;
