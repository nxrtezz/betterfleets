import { View, Text, StyleSheet } from 'react-native';

export default function AccessDeniedScreen() {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>Access Denied</Text>
      <Text style={styles.subtitle}>
        You do not have permission to use the Overland tracking feature.
      </Text>
      <Text style={styles.info}>
        Please contact a BetterFleets administrator if you believe this is an error.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#fff',
    padding: 20,
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    marginBottom: 20,
    color: '#f00',
  },
  subtitle: {
    fontSize: 16,
    color: '#333',
    textAlign: 'center',
    marginBottom: 10,
  },
  info: {
    fontSize: 14,
    color: '#666',
    textAlign: 'center',
  },
});
