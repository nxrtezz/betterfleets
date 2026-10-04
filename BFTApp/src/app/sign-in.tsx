import { View, Text, StyleSheet } from 'react-native';
import { SignIn } from '@clerk/expo';

export default function SignInScreen() {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>BetterFleets Tracking</Text>
      <Text style={styles.subtitle}>
        Sign in with your BetterFleets account to access tracking features
      </Text>
      <View style={styles.signInContainer}>
        <SignIn />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
    backgroundColor: '#fff',
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    marginBottom: 20,
  },
  subtitle: {
    fontSize: 16,
    marginBottom: 30,
    textAlign: 'center',
    color: '#666',
  },
  signInContainer: {
    width: '100%',
  },
});
